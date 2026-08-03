"""AI 分析契约：输入/输出路径 + schema 版本 + 语言（单一事实源，架构 §1.5）。

文件形态约定（重要，架构 §3.3/§3.4）：
- facts.json / analysis.zh-CN.json / analysis.en.json / news.zh-translations.json
  为**自描述契约文件**（自带 schema_version/generated_at/language），直接以对应模型解析，
  不额外包裹 BaseEnvelope（避免元数据重复）。
- 其余数据集文件（macro/equities/…/risk.json）一律包裹 BaseEnvelope。
"""

from __future__ import annotations

from pathlib import Path

from pipeline.schemas.envelope import SCHEMA_VERSION
from pipeline.settings import settings

SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh-CN", "en")

# 输出目录：public/data/latest（架构 §1.5）
ANALYSIS_DIR: Path = settings.data_dir / "latest"

# 输入（管道产出，确定性）
INPUT_FILES: dict[str, Path] = {
    "facts": ANALYSIS_DIR / "facts.json",
    "news": ANALYSIS_DIR / "news.json",
}

# 输出（AI 自动化产出，经校验）
OUTPUT_FILES: dict[str, Path] = {
    "analysis_zh": ANALYSIS_DIR / "analysis.zh-CN.json",
    "analysis_en": ANALYSIS_DIR / "analysis.en.json",
    "news_translations": ANALYSIS_DIR / "news.zh-translations.json",
}


def input_path(name: str) -> Path:
    """输入文件路径（name: 'facts' | 'news'）。"""
    if name not in INPUT_FILES:
        raise KeyError(f"未知输入契约: {name!r}，可选: {sorted(INPUT_FILES)}")
    return INPUT_FILES[name]


def output_path(name: str) -> Path:
    """输出文件路径（name: 'analysis_zh' | 'analysis_en' | 'news_translations'）。"""
    if name not in OUTPUT_FILES:
        raise KeyError(f"未知输出契约: {name!r}，可选: {sorted(OUTPUT_FILES)}")
    return OUTPUT_FILES[name]


def analysis_path(lang: str) -> Path:
    """按语言返回分析文件路径。"""
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"不支持的语言: {lang!r}，可选: {SUPPORTED_LANGUAGES}")
    return ANALYSIS_DIR / f"analysis.{lang}.json"


def expected_interval_minutes(dataset: str, fallback: int = 720) -> int:
    """期望更新间隔（分钟）。

    优先读 config/sources.yaml expectations；缺失时返回 fallback。
    冻结频率（架构 §8.5）：行情/新闻 480、宏观 240、日历 1440、分析 720。
    """
    try:
        sources = settings.load_sources()
        expectations = sources.get("expectations", {})
        entry = expectations.get(dataset, {})
        minutes = int(entry.get("interval_minutes", fallback))
        return minutes if minutes > 0 else fallback
    except (FileNotFoundError, ValueError, TypeError):
        return fallback
