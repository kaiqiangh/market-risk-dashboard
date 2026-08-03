#!/usr/bin/env bash
# 本地定时任务执行脚本（docs/operations/scheduled-task.md §3 落地）。
# 流程：git pull → 管道运行 → 数据校验 → 实质变化检查 → commit + push。
#
# 用法：scripts/run_scheduled.sh [--full|--market-only|--macro-only|--news-only|--fact-layer]
# 默认 --full。断网/失败时按 §4 降级：不中断、不静默、留日志。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:---full}"

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) 开始，模式 $MODE"

# 0) 环境准备（拉取最新，含 AI 简报与其他协作者提交）
if ! git pull --rebase origin dev 2>/dev/null; then
  echo "[scheduled] 警告：git pull 失败（可能断网），继续使用本地状态" >&2
fi

# 1) 运行管道（任一 Provider 失败不中断，见架构 §8）
if ! .venv/bin/python -m pipeline.run "$MODE"; then
  echo "[scheduled] 错误：管道运行失败，详见 artifacts/logs/run-report-*.json" >&2
  exit 1
fi

# 2) 数据校验（T05 门槛；ERROR 时不提交）
if ! scripts/validate_data.sh; then
  echo "[scheduled] 错误：数据校验未通过，不提交" >&2
  exit 1
fi

# 3) 实质变化检查 + 提交（避免无意义 Actions 触发，架构 §8.14）
if git diff --quiet public/ config/; then
  echo "[scheduled] 无实质变化，跳过提交"
  exit 0
fi

git add public/ config/
git commit -m "data: scheduled update $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null || true

if ! git push origin dev; then
  echo "[scheduled] 错误：push 失败（网络/冲突），本地已提交，请稍后 git pull --rebase 后重推" >&2
  exit 1
fi

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) 完成"
