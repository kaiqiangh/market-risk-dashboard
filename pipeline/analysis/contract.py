"""AI analysis contract: input/output paths + schema version + languages (single source of truth, architecture §1.5).

File shape conventions (important, architecture §3.3/§3.4):
- facts.json / analysis.zh-CN.json / analysis.en.json / news.zh-translations.json
  are **self-describing contract files** (carry schema_version/generated_at/language), parsed
  directly with their own models, without wrapping in BaseEnvelope (avoids duplicate metadata).
- All other dataset files (macro/equities/…/risk.json) are wrapped in BaseEnvelope.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.schemas.envelope import SCHEMA_VERSION
from pipeline.settings import settings

SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh-CN", "en")

# Output directory: public/data/latest (architecture §1.5)
ANALYSIS_DIR: Path = settings.data_dir / "latest"

# Input (pipeline-produced, deterministic)
INPUT_FILES: dict[str, Path] = {
    "facts": ANALYSIS_DIR / "facts.json",
    "news": ANALYSIS_DIR / "news.json",
}

# Output (produced by AI automation, validated)
OUTPUT_FILES: dict[str, Path] = {
    "analysis_zh": ANALYSIS_DIR / "analysis.zh-CN.json",
    "analysis_en": ANALYSIS_DIR / "analysis.en.json",
    "news_translations": ANALYSIS_DIR / "news.zh-translations.json",
}


def input_path(name: str) -> Path:
    """Input file path (name: 'facts' | 'news')."""
    if name not in INPUT_FILES:
        raise KeyError(f"unknown input contract: {name!r}, options: {sorted(INPUT_FILES)}")
    return INPUT_FILES[name]


def output_path(name: str) -> Path:
    """Output file path (name: 'analysis_zh' | 'analysis_en' | 'news_translations')."""
    if name not in OUTPUT_FILES:
        raise KeyError(f"unknown output contract: {name!r}, options: {sorted(OUTPUT_FILES)}")
    return OUTPUT_FILES[name]


def analysis_path(lang: str) -> Path:
    """Return the analysis file path for a language."""
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {lang!r}, options: {SUPPORTED_LANGUAGES}")
    return ANALYSIS_DIR / f"analysis.{lang}.json"


def expected_interval_minutes(dataset: str, fallback: int = 720) -> int:
    """Expected update interval (minutes) for a dataset.

    Kept as a named function because the analysis layer imports it, but it no longer reads the
    config itself: this was the second of three independent implementations of the same lookup
    (D-2), and the one whose different default (720 vs 480) meant the analysis layer and the
    envelope could disagree about whether the same file was late.
    """
    from pipeline.validation.freshness import expected_interval_minutes_for

    return expected_interval_minutes_for(dataset, fallback)
