"""Validated config models (#102, decision #90, ADR 0005: config is a fact).

One pydantic model per config file, all loaded through :func:`load_config`, which raises
:class:`ConfigError` **before any provider is constructed**. Every model uses
``extra="forbid"`` so a typo'd key fails loudly instead of silently disabling a theme or
silently keeping a dead knob.

Scope: the configs #102 actually touches — ``sources.yaml``, ``universe.yaml``,
``themes.yaml``, ``news_sources.yaml``. ``risk_model.yaml`` is deliberately not modelled
here: it is already validated by ``pipeline/risk/model.py`` (pinned by
``tests/pipeline/test_config_drift.py``), and modelling it twice would create a second
authoritative shape for the same file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypeVar
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from pipeline.degrade import DEFAULT_CACHE_MAX_AGE_HOURS, DEFAULT_DEGRADE_FACTOR


#: Everything config-related that #102 can raise. Loaders use it so a bad config fails the
#: run at construction time rather than surfacing mid-collection as a confusing provider
#: error.
class ConfigError(Exception):
    """A config file is missing, unparseable, or failed pydantic validation."""


# -------------------------------------------------------------------------------------
# sources.yaml
# -------------------------------------------------------------------------------------


class Expectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_minutes: int = Field(ge=1)
    note: str | None = None


class ProviderEntry(BaseModel):
    """One provider in the degradation chain. ``max_concurrency``/``min_interval_ms`` are
    the per-host token-bucket budget used by the registry's rate limiter (#103/P-1): a
    browser-hostile host like Yahoo gets the tightest budget."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    priority: int = Field(ge=0)
    enabled: bool = True
    max_concurrency: int = Field(default=2, ge=1)
    min_interval_ms: int = Field(default=500, ge=0)


class DegradeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=2, ge=0)
    backoff_base_seconds: float = Field(default=1.0, gt=0)
    jitter: bool = True
    cache_max_age_hours: float = Field(default=DEFAULT_CACHE_MAX_AGE_HOURS, gt=0)
    data_quality_degrade_factor: float = Field(default=DEFAULT_DEGRADE_FACTOR, gt=0, le=1.0)
    last_good_cache_dir: str = Field(default="artifacts/cache", min_length=1)


class OperationsConfig(BaseModel):
    """Tuning knobs that used to be magic literals in the collectors (M-5).

    Model parameters (4.0/105/1.5, fact-layer slices 15/20/5/8) deliberately stay in Python
    as named constants with a derivation comment — they are model parameters, not operations
    knobs, and moving them would put model math behind a config indirection.
    """

    model_config = ConfigDict(extra="forbid")

    circuit_breaker_threshold: int = Field(default=2, ge=1, description="per-domain failures before the collector fast-degrades")
    calendar_horizon_days: int = Field(default=14, ge=1)
    news_max_items: int = Field(default=50, ge=1)
    news_summary_max_chars: int = Field(default=160, ge=1, description="copyright-boundary summary cap")
    recency_half_life_hours: float = Field(default=48.0, gt=0)


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    expectations: dict[str, Expectation] = Field(default_factory=dict)
    providers: dict[str, list[ProviderEntry]] = Field(default_factory=dict)
    degrade: DegradeConfig = Field(default_factory=DegradeConfig)
    operations: OperationsConfig = Field(default_factory=OperationsConfig)


# -------------------------------------------------------------------------------------
# universe.yaml
# -------------------------------------------------------------------------------------


class UniverseAsset(BaseModel):
    """One asset-pool entry. No ``theme`` field: membership lives in themes.yaml (D-8)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    name: str = Field(min_length=1)
    name_zh: str | None = None
    sector: str = "other"


class UniverseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "1.0.0"
    us_equities: list[UniverseAsset] = Field(default_factory=list)
    a_share_memory: list[UniverseAsset] = Field(default_factory=list)
    crypto: list[UniverseAsset] = Field(default_factory=list)
    metals: list[UniverseAsset] = Field(default_factory=list)
    oil: list[UniverseAsset] = Field(default_factory=list)
    # #93: theme-series-only assets — fetched for basket percentile series, never rendered
    # as equity cards (the collector's `all_equities()` stays us + a_share).
    theme_series: list[UniverseAsset] = Field(default_factory=list)


# -------------------------------------------------------------------------------------
# themes.yaml
# -------------------------------------------------------------------------------------


class ThemeProxy(BaseModel):
    """An optional market proxy for a theme (#86: 11 ETF-proxied themes, 9 basket themes)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["etf", "basket"]
    symbol: str | None = None


class ThemePercentile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_sessions: int = Field(default=252, ge=1)
    window_sessions: int = Field(default=20, ge=1)
    min_observations: int = Field(default=100, ge=1)


class ThemeConstituent(BaseModel):
    """``weight``: 1.0 primary, 0.5 secondary (#86). Must resolve in universe.yaml."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1)
    weight: float = Field(default=1.0, gt=0)


class ThemeDef(BaseModel):
    """One theme (#93/#86). ``proxy`` with ``kind: etf`` publishes the ETF's own series;
    ``kind: basket`` (or no proxy) builds an equal-weight series from constituents.
    ``weight`` 1.0 primary / 0.5 secondary."""

    model_config = ConfigDict(extra="forbid")

    proxy: ThemeProxy | None = None
    percentile: ThemePercentile | None = None
    constituents: list[ThemeConstituent] = Field(default_factory=list)


class ValidationConfig(BaseModel):
    """#93/#86 taxonomy guards — enforced at config load (hard fails)."""

    model_config = ConfigDict(extra="forbid")

    max_primaries_per_symbol: int = Field(default=1, ge=1)
    max_themes_per_symbol: int = Field(default=3, ge=1)
    max_pairwise_jaccard: float = Field(default=0.40, gt=0, le=1.0)


class ThemesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1)
    #: Global percentile defaults (window/lookback/min_obs); per-theme overrides win.
    percentile: ThemePercentile | None = None
    validation: ValidationConfig | None = None
    sectors: dict[str, ThemeDef] = Field(default_factory=dict)
    themes: dict[str, ThemeDef] = Field(default_factory=dict)


# -------------------------------------------------------------------------------------
# news_sources.yaml
# -------------------------------------------------------------------------------------


class NewsSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    lang: Literal["en", "zh"] = "en"
    weight: int = Field(default=1, ge=0)
    category: str | None = None
    enabled: bool = True
    # #124: ordered fallback URL chain — a dead primary advances to the first fallback that
    # serves; one try per URL per run attempt. Every URL is https-only (S-3) and a chain
    # holds no exact duplicates (config-is-a-fact, ADR-0005).
    fallback_urls: list[str] = Field(default_factory=list)
    # S-3: a relay source (rsshub.app) is allowed to redirect anywhere — it is trusted as a
    # forwarding relay, not as a terminal host.
    trust: Literal["relay"] | None = None

    @model_validator(mode="after")
    def _chain_is_https_and_duplicate_free(self) -> "NewsSource":
        seen: set[str] = set()
        for url in self.chain_urls:
            if urlparse(url).scheme != "https":
                raise ValueError(f"news source URL must be https: {url!r}")
            if url in seen:
                raise ValueError(f"duplicate URL in news source chain: {url!r}")
            seen.add(url)
        return self

    @property
    def chain_urls(self) -> list[str]:
        """Primary URL first, then each fallback — the ordered chain the provider walks
        (#124). One shape for the validator, the S-3 allowlist, and the fetch loop."""
        return [self.url, *self.fallback_urls]


class NewsImportance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_weight: float = Field(default=30, ge=0)
    keyword_weight: float = Field(default=30, ge=0)
    asset_hit_weight: float = Field(default=20, ge=0)
    recency_weight: float = Field(default=20, ge=0)
    keywords: dict[str, list[str]] = Field(default_factory=dict)


class NewsSourcesConfig(BaseModel):
    """No ``assets``/``categories`` blocks: asset hits come from the universe (D-8), and the
    category list was dead config (no consumer ever read it)."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0.0"
    sources: list[NewsSource] = Field(default_factory=list)
    importance: NewsImportance = Field(default_factory=NewsImportance)


# -------------------------------------------------------------------------------------
# The single loader
# -------------------------------------------------------------------------------------

M = TypeVar("M", bound=BaseModel)


def load_config(path: Path, model: type[M]) -> M:
    """Load and validate one config file. Raises :class:`ConfigError` on any failure."""
    if not path.exists():
        raise ConfigError(f"config file missing: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must be a YAML mapping: {path}")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"config file failed validation ({path}): {exc}") from exc
