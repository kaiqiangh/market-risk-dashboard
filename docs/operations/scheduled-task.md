# 本地 Scheduled Task 运维手册

**适用：** 数据管道本机定时任务（Windows 任务计划程序 / macOS launchd / cron）。
**目标：** 每天 2-3 次自动采集 → 计算 → 校验 → push，保持 `public/data` 新鲜，驱动 GitHub Pages 自动部署。

---

## 1. 运行节奏

按美股交易日（ET）安排，每天 2-3 次；非交易日（周末/美股节假日）可跳过行情采集，但可保留新闻采集。

| 时段 | ET 时间 | 命令 | 目的 |
|---|---|---|---|
| 盘前 | 07:30 ET | `python -m pipeline.run --full` | 隔夜宏观/新闻 + 盘前状态快照 |
| 盘后 | 16:30 ET | `python -m pipeline.run --full` | 当日收盘行情 + 风险模型更新 |
| 隔夜（可选） | 23:30 ET | `python -m pipeline.run --news-only` 或 `--full` | 亚洲时段新闻/隔夜行情补充 |

**ET ↔ 本地时间映射：** 在 `.env` 或任务计划中按本机时区换算（示例：ET 07:30 = UTC 11:30（夏令时）/ 12:30（冬令时），北京 19:30/20:30 次日）。

> 说明：行情/新闻期望频率 2-3 次/日（架构 §8.5），宏观 FRED 为 T+1 发布节奏；`freshness` 判定见 `pipeline/validation/freshness.py`。

## 2. CLI 命令集（冻结）

```bash
cd /path/to/market-risk-dashboard

# 全量（默认）：采集 + 指标 + 6 维风险 + 事实层 + 校验 + 写盘
python -m pipeline.run --full

# 分域
python -m pipeline.run --market-only     # 行情 + 加密 + A股
python -m pipeline.run --macro-only      # FRED + FedWatch
python -m pipeline.run --news-only       # RSS 新闻
python -m pipeline.run --fact-layer      # 只重建事实层（不采集）

# 其他
python -m pipeline.run --dry-run         # 试跑不写盘
python -m pipeline.run --backfill        # 预热回填 30-90 天历史
```

建议使用项目 venv：`.venv/bin/python -m pipeline.run --full`。

## 3. 标准流程（git pull → run → commit → push）

每次任务执行脚本（`scripts/run_scheduled.sh`，见文末示例）应包含：

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 0) 环境准备
git pull --rebase origin dev          # 拉取最新（含 AI 简报、其他协作者的提交）

# 1) 运行管道
.venv/bin/python -m pipeline.run --full || { echo "管道失败，见 artifacts/logs/"; exit 1; }

# 2) 数据校验（T05 门槛）
scripts/validate_data.sh || { echo "数据校验失败，不提交"; exit 1; }

# 3) 实质变化检查 + 提交（避免无意义 Actions 触发，架构 §8.14）
if git diff --quiet public/ config/ metadata/; then
  echo "无实质变化，跳过提交"
  exit 0
fi
git add public/ config/
git commit -m "data: scheduled update $(date -u +%Y-%m-%dT%H:%M:%SZ)" || exit 0
git push origin dev
```

## 4. 断网 / 失败降级行为

| 场景 | 管道行为 | 运维动作 |
|---|---|---|
| 某 Provider 失败 | 走降级链（备用 → last-good 缓存 → `degraded`），**不中断整条管道** | 无需干预；查看 `metadata/sources.json` |
| 全部行情源失败 | 保留最近一次有效数据 + `freshness=missing/stale` 标记 | 检查网络/代理；必要时手动 `--market-only` 重试 |
| 本机断网 | 管道异常退出，无新数据 | 下个计划时间自动重试；无需人工 |
| git push 失败（网络/冲突） | 数据已写入本地但未上库 | `git pull --rebase` 后重推；若数据过期前端会显示 stale |
| AI 简报缺失 | 分析数据集 `freshness=degraded`，前端 AI 区块降级 | 按 `docs/operations/ai-analysis-automation.md` 演练 |

**原则（架构 §1.1/#8）：** 管道异常**不得中断整条管道**；多源降级是默认路径而非异常路径；任何失败都不得产生静默错误（写 `artifacts/logs/run-report-*.json`）。

## 5. .env 密钥管理

- `.env` 已被 gitignore（含 `DATA_FRED_API_KEY` / `DATA_COINGECKO_API_KEY` / `DATA_FMP_API_KEY`）。
- **密钥只在本机**，绝不提交；前端/CI 不得出现 key（架构 §8.13/PRD §24）。
- 轮换：修改 `.env` 后重启下次任务即可；无需改代码。
- 备份：密钥可存密码管理器；换机部署时复制 `.env` 到新机（保持 gitignore 不变）。
- 无 key 时管道仍可运行：FRED/CoinGecko/FMP 对应 Provider 会降级/跳过，其余数据照常。

## 6. 恢复与排障

1. 查看最新运行报告：`ls -t artifacts/logs/run-report-*.json | head -1`
2. 查看 Provider 健康：`cat public/data/metadata/sources.json`
3. 手动重试：`scripts/validate_data.sh && python -m pipeline.run --full`
4. 数据过期修复：确认本机时间/时区正确（调度按 ET，写入按 UTC ISO 8601）。
5. 任务计划程序（Windows）：触发器设置"工作日 07:30/16:30/23:30"，操作 `cmd /c scripts\run_scheduled.bat`。
6. macOS：可用 launchd plist 或 `crontab`，日志重定向到 `artifacts/logs/cron.log`。

## 7. 示例脚本

完整示例见仓库 `scripts/run_scheduled.sh`（可复制到任务计划引用）。
