# WorkBuddy AI 自动化接入手册

**适用：** WorkBuddy 定时自动化（deepseek v4 flash）在管道之外生成双语 AI 简报。
**契约：** 输入/输出均为磁盘文件（架构 §1.5）；管道保持确定性与可重放，AI 是"可插拔的外部步骤"。

---

## 1. 每日节奏（冻结）

| 时段 | ET 时间 | 触发条件 |
|---|---|---|
| 盘前 | 07:30 ET | 管道盘前运行后（facts.json 已更新） |
| 盘后 | 16:30 ET | 管道盘后运行后 |

每天 2 次。无额度/失败时跳过该步并标记 degraded（见 §5 演练）。

## 2. 输入 / 输出契约

**输入（管道产出，确定性）：**

| 文件 | 说明 |
|---|---|
| `public/data/latest/facts.json` | 事实层：风险结果 + 宏观/市场摘要 + Top 新闻 + 未来 7 天事件 + `evidence_index` |
| `public/data/latest/news.json` | 新闻（含英文原始标题） |

**输出（AI 产出，经校验）：**

| 文件 | 说明 |
|---|---|
| `public/data/latest/analysis.zh-CN.json` | 中文简报（AnalysisDataset schema） |
| `public/data/latest/analysis.en.json` | 英文简报（AnalysisDataset schema） |
| `public/data/latest/news.zh-translations.json` | 英文新闻中译（title_zh/summary_zh） |

**工具（仓库内，自动化按顺序调用）：**

```bash
# 1) 事实层 → 双语文案 prompt
python -m pipeline.analysis.build_prompt --lang zh-CN    # 中文 prompt
python -m pipeline.analysis.build_prompt --lang en       # 英文 prompt

# 2) 输出校验（schema + evidence_refs + 双语一致性）
python -m pipeline.analysis.validate \
  --zh public/data/latest/analysis.zh-CN.json \
  --en public/data/latest/analysis.en.json \
  --facts public/data/latest/facts.json

# 3) 新鲜度检查（供自动化决策是否跳过）
python -m pipeline.analysis.freshness --dataset facts
```

## 3. 自动化步骤（WorkBuddy 触发器）

1. `git pull --rebase origin dev`（拉取最新 facts.json）。
2. 检查 `facts.json` 新鲜度（`pipeline.analysis.freshness`）：stale 仍可生成，但输出带 `data_freshness` 标注。
3. `build_prompt.py` 出 prompt（中/英各一次，含证据索引片段）。
4. 调用 deepseek v4 flash 生成三份输出（中文简报 / 英文简报 / 新闻中译）。
5. `pipeline.analysis.validate` 校验：
   - Schema 合法（禁隐式字段/NaN/枚举/时间）
   - 每个 `evidence_refs` 都能在 `evidence_index` 中找到
   - **双语一致性**：`market_state` / `market_regime` / `confidence` / `evidence_refs` 集合 / 文本中所有数字必须完全一致；仅表达语言可不同
   - 失败重试 ≤2 次（重新生成或局部修正）。
6. 写三个输出文件 → `git commit + push (dev)` → 触发 Pages 构建。

**双语一致性规则（架构 §3.4）：** 不一致 → 拒绝发布；宁可跳过本次也不发布错误结论。

## 4. 校验失败 / 无额度降级演练

**场景 A：校验失败且重试耗尽**

1. 不写任何分析文件，不 push。
2. 保留上次成功发布的分析文件（前端继续展示旧简报 + stale 标记）。
3. 管道下次运行在 `metadata/freshness.json` 将分析数据集标记 `degraded`（原因 `analysis_failed`）。
4. 前端 AI 区块显示降级而非缺失。

**场景 B：无额度（quota exhausted）**

1. 跳过生成步骤（不调用 LLM）。
2. 同上：不 push 分析文件，标记 `degraded`。
3. 恢复额度后，下个计划时间自动恢复；也可手动触发一次盘后自动化。

**演练检查清单：**

- [ ] `git status` 无未推送的分析文件残留
- [ ] `metadata/freshness.json` 中 `analysis` 数据集为 `degraded`
- [ ] 前端 AI 区块显示"部分降级"而非崩溃/空白
- [ ] `scripts/validate_data.sh` 仍通过（AI 缺失是 WARNING 不是 ERROR）

## 5. 手动演练步骤（验证整条链路）

```bash
cd /path/to/market-risk-dashboard
git pull --rebase origin dev

# 1) 确认事实层新鲜
.venv/bin/python -m pipeline.analysis.freshness --dataset facts

# 2) 生成 prompt（确认模板可用）
.venv/bin/python -m pipeline.analysis.build_prompt --lang zh-CN > /tmp/prompt-zh.txt
.venv/bin/python -m pipeline.analysis.build_prompt --lang en    > /tmp/prompt-en.txt

# 3) 用 deepseek v4 flash 按 prompt 生成（WorkBuddy 自动化内完成）
#    输出写 public/data/latest/analysis.zh-CN.json / analysis.en.json / news.zh-translations.json

# 4) 校验
.venv/bin/python -m pipeline.analysis.validate \
  --zh public/data/latest/analysis.zh-CN.json \
  --en public/data/latest/analysis.en.json \
  --facts public/data/latest/facts.json

# 5) 全量数据校验（T05 门槛）
scripts/validate_data.sh

# 6) 提交推送
git add public/data/latest/analysis.zh-CN.json public/data/latest/analysis.en.json public/data/latest/news.zh-translations.json
git commit -m "ai: bilingual brief $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin dev
```

## 6. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| validate 报 schema 错误 | AI 输出缺字段/枚举非法 | 用输出 schema 字段清单核对；重试生成 |
| validate 报 evidence_ref 不存在 | AI 引用了 evidence_index 之外的证据 | 只允许引用 prompt 提供的证据片段；重新生成 |
| 双语数字不一致 | 中英文本数字不同（如 3.2 与 3.20） | 统一保留原始数值；重试 |
| 无额度 | deepseek 额度耗尽 | 跳过 + degraded（见 §4） |
| facts 长时间 stale | 管道未运行 | 先跑管道（`docs/operations/scheduled-task.md`） |

## 7. 维护说明

- 换模型/换自动化平台**不动管道**：只改本手册步骤 3-4 的调用。
- 新闻中译文件由管道下次运行合并进 `news.json`（`pipeline/collectors/news.py` merge 步骤），保证单一事实源；自动化**不要**直接改 `news.json`。
- 术语遵循 `docs/glossary.md`；prompt 模板 `pipeline/analysis/build_prompt.py` 已内嵌关键术语映射。
