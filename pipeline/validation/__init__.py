"""Validation package (architecture §3.7 Validator)."""

from pipeline.validation.freshness import evaluate_freshness
from pipeline.validation.validate_all import ValidationReport, validate_all, validate_file

__all__ = [
    "CheckReport",
    "ValidationReport",
    "evaluate_freshness",
    "run_all",
    "run_latest",
    "validate_all",
    "validate_file",
]


def __getattr__(name: str):
    """Lazily preserve the historical package-level validation exports.

    Importing ``ci_checks`` eagerly makes ``python -m pipeline.validation.ci_checks`` load the
    module before runpy executes it, producing a warning and obscuring real CI output.
    """
    if name in {"CheckReport", "run_all", "run_latest"}:
        from pipeline.validation import ci_checks

        return getattr(ci_checks, name)
    if name in {"ValidationReport", "validate_all", "validate_file"}:
        return globals()[name]
    raise AttributeError(name)
