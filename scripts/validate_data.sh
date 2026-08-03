#!/usr/bin/env bash
# 本地一键数据校验（架构 §5#1 / PRD §20.2）。
# 等价于 .github/workflows/validate-data.yml 的检查项，供本地 Scheduled Task / 开发机使用：
#   Schema 校验 / 必填字段 / 时间戳 / 数据质量 / 风险分数范围 / NaN·Infinity /
#   重复新闻 / 数据过期 / 未知语言 key / 中英文缺失 / AI 双语结论不一致。
#
# 用法：
#   scripts/validate_data.sh [--data-dir <public/data>]
#
# 退出码：0 = 通过（可含 WARNING）；1 = 存在 ERROR。
# 优先使用 .venv/bin/python（完整 Pydantic 校验）；无 pydantic 时降级为 Node 结构校验。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 定位 Python 解释器
PY=""
for candidate in ".venv/bin/python" ".venv/Scripts/python.exe"; do
  if [[ -x "$candidate" ]]; then
    PY="$candidate"
    break
  fi
done
if [[ -z "$PY" ]]; then
  PY="$(command -v python3 || true)"
fi
if [[ -z "$PY" ]]; then
  echo "[validate_data] 错误：未找到 Python 3（需要 .venv/bin/python 或系统 python3）" >&2
  exit 1
fi

# 完整校验（Pydantic 可用）
if "$PY" -c "import pydantic, yaml, pydantic_settings" >/dev/null 2>&1; then
  exec "$PY" -m pipeline.validation.ci_checks "$@"
fi

# 降级：Node 结构校验（无需 Python 依赖）
if command -v node >/dev/null 2>&1 && [[ -f scripts/validate-json.mjs ]]; then
  echo "[validate_data] 警告：pydantic 未安装，降级为 Node 结构校验（覆盖 Schema/必填/范围/NaN/重复，不含双语一致性）" >&2
  exec node scripts/validate-json.mjs "$@"
fi

echo "[validate_data] 错误：pydantic 与 node 均不可用，无法校验" >&2
exit 1
