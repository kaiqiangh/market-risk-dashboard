"""AI 分析契约工具包（架构 §1.5 WorkBuddy 自动化）。

- contract.py：输入/输出路径 + schema 版本 + 语言（单一事实源）
- build_prompt.py：facts.json → 双语 prompt 模板
- validate.py：输出 schema + 双语一致性 + evidence_refs 校验（CLI）
- freshness.py：分析新鲜度检查（供自动化决策是否跳过）
"""

from .contract import (
    ANALYSIS_DIR,
    INPUT_FILES,
    OUTPUT_FILES,
    SCHEMA_VERSION,
    SUPPORTED_LANGUAGES,
    analysis_path,
    expected_interval_minutes,
    input_path,
    output_path,
)

__all__ = [
    "ANALYSIS_DIR",
    "INPUT_FILES",
    "OUTPUT_FILES",
    "SCHEMA_VERSION",
    "SUPPORTED_LANGUAGES",
    "analysis_path",
    "expected_interval_minutes",
    "input_path",
    "output_path",
]
