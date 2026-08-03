"""AI analysis contract toolkit (architecture §1.5 WorkBuddy automation).

- contract.py: input/output paths + schema version + languages (single source of truth)
- build_prompt.py: facts.json → bilingual prompt template
- validate.py: output schema + bilingual consistency + evidence_refs validation (CLI)
- freshness.py: analysis freshness check (for automation to decide whether to skip)
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
