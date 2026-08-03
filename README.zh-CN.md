# 市场风险情报看板

**全球市场风险情报看板** —— 面向个人投资研究的跨资产、双语（中文/英文）市场风险情报看板。
本地数据管道产出确定性的结构化事实层，可选的 AI 步骤生成双语简报，静态站点负责发布。

> ⚠️ 风险分数为**模型化的市场压力估计**，并非精确的崩盘概率，不构成投资建议。

## 运行手册

### 前端

```bash
npm install
npm run dev      # 本地开发（http://localhost:5173）
npm run build    # 生产构建 → dist/
npm test         # vitest（契约测试）
```

### 管道

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pipeline.run --dry-run   # 配置自检 + 计划输出，no-op 正常退出
python -m pytest tests/pipeline/ -v
```

许可证：MIT —— 见 [LICENSE](LICENSE)。
