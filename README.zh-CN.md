# 市场风险情报看板

**全球市场风险情报看板** —— 面向个人投资研究的跨资产、双语（中文/英文）市场风险情报看板。
静态优先：本地数据管道产出确定性的结构化事实层，可选的 AI 步骤生成双语简报，GitHub Pages 负责发布。

> ⚠️ 风险分数为**模型化的市场压力估计**，并非精确的崩盘概率，不构成投资建议。

## 架构

详见 `docs/architecture.md`（内部文档）。数据流概览：

```
本地管道（定时任务）→ facts.json（确定性事实层）
  → AI 分析（WorkBuddy 自动化，可选）→ analysis.zh-CN/en.json
  → git push (dev) → GitHub Actions（仅构建+部署）→ GitHub Pages
```

Schema 三件套：JSON Schema（数据文件契约）+ Zod（前端运行时）+ Pydantic（管道运行时）——
同一份语义、三处落地，任何一侧校验失败都不得发布。

## 快速开始

### 前端

```bash
npm install
npm run dev        # 本地开发（http://localhost:5173）
npm run build      # 生产构建 → dist/
npm test           # vitest（Zod 契约测试）
```

### 管道

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pipeline.run --dry-run   # 骨架：配置自检 + 计划输出，no-op 正常退出
python -m pytest tests/pipeline/ -v
```

将 `.env.example` 复制为 `.env` 并填入 API key（仅本机使用，已 gitignore）。

## 仓库结构

```
config/            管道运行时配置（资产池 / 风险模型 / 数据源 / 新闻源）
pipeline/          数据管道（schemas、AI 契约、providers、collectors…）
public/data/       前端消费的静态数据（管道 + AI 产出）
src/               React 前端（页面、组件、图表、i18n、lib）
tests/             fixtures + 管道/前端/i18n 测试
.github/workflows/ 仅构建+部署（不采集数据、无 Secrets）
```

## 里程碑

- **T01** 项目基础设施（本骨架）
- **T02** 数据契约层（Pydantic + Zod + AI 契约 + fixtures）
- **T03** 数据管道（providers → 指标 → 6 维风险 → 事实层 → 存储）
- **T04** 前端 UI（8 个页面、i18n、主题、图表）
- **T05** 集成、校验、校准报告、部署

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
