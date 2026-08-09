"""Compatibility facade for the canonical :mod:`pipeline.validation.ci_checks` validator.

The pipeline historically imported ``validate_all`` and ``validate_file`` from this module.
Those names remain stable for callers and tests, while all validation semantics now live in one
composed Python entry point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    DATASET_MODELS: dict[str, tuple[Any, str]]
    STANDALONE_MODELS: dict[str, Any]

__all__ = [
    "DATASET_MODELS",
    "STANDALONE_MODELS",
    "ValidationReport",
    "validate_all",
    "validate_file",
    "main",
]


def __getattr__(name: str) -> Any:
    """Lazily expose the old model-view names without importing the canonical runner."""
    if name == "DATASET_MODELS":
        from pipeline.validation.ci_checks import ENVELOPE_MODELS

        return ENVELOPE_MODELS
    if name == "STANDALONE_MODELS":
        from pipeline.validation.ci_checks import STANDALONE_MODELS

        return STANDALONE_MODELS
    raise AttributeError(name)


@dataclass
class ValidationReport:
    ok: bool = True
    files_checked: int = 0
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_issue(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)


def validate_file(path: Path) -> list[str]:
    """Validate one file through the canonical implementation."""
    from pipeline.validation.ci_checks import validate_file as validate_canonical_file

    return validate_canonical_file(path)


def validate_all(latest_dir: Path, strict: bool = True) -> ValidationReport:
    """Validate every registered dataset under ``latest/``, and refuse to ignore strangers.

    Two directions, both required (S-4):

    - **every registered file must be present and valid** — subject to ``spec.required``, since
      the AI-authored files (``analysis.*``, ``news.zh-translations.json``) are produced by a
      different automation and their absence is a degraded mode, not a broken run
    - **every file present must be registered** — previously an unregistered file was simply
      never looked at, which is how 7 of 25 published files went unvalidated while the log
      cheerfully reported "checked 18 files"

    ``strict=False`` is retained for callers of the historical API; requiredness is still
    fail-closed and comes from the canonical registry. Optional AI-authored files remain a
    degraded warning when absent.
    """
    from pipeline.validation.ci_checks import run_latest

    canonical = run_latest(latest_dir)
    # The old facade treated stale data as an issue via validate_file. The canonical report marks
    # that severity explicitly, so no message-text policy needs to be duplicated here.
    issues = [*canonical.errors, *canonical.blocking_warnings]
    return ValidationReport(
        ok=not issues,
        files_checked=canonical.files_checked,
        issues=issues,
        warnings=[warning for warning in canonical.warnings if warning not in canonical.blocking_warnings],
    )


def main(latest_dir: str | None = None) -> int:
    from pipeline.settings import settings

    target = Path(latest_dir) if latest_dir else settings.data_dir / "latest"
    report = validate_all(target, strict=False)
    print(f"[validate_all] checked {report.files_checked} files, {len(report.issues)} issue(s)")
    for issue in report.issues:
        print(f"  - {issue}")
    return 0 if report.ok else 1
