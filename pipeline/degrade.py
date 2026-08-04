"""The data-quality degrade factor: one definition, one config key, one accessor (ADR 0004/0005).

The degrade factor answers a single question — by how much does published `data_quality`
drop for each input that had to fall back to a secondary provider, come off the last-good
cache, or fail outright?

Before this module the answer lived in six places: one config read in
`providers/base.py` that nothing consumed, and five hardcoded literals in the collectors
and in `risk/confidence.py`. Editing `degrade.data_quality_degrade_factor` in
`config/sources.yaml` therefore moved nothing at all. Every consumer now resolves the
factor through :func:`degrade_factor`, which makes that config key a fact rather than
documentation.

Compounding is deliberate and predates this module: *n* failed sources cost ``factor ** n``,
not ``factor``. Two independent failures should hurt more than one.
"""

from __future__ import annotations

import math
from typing import Any

from pipeline.settings import Settings

#: The only degrade-factor literal in the pipeline. `config/sources.yaml` normally supplies
#: the value; this is the fallback used when the key — or the whole section — is absent.
DEFAULT_DEGRADE_FACTOR = 0.8

#: Published `data_quality` never drops below this, however many inputs degraded. A run that
#: salvaged something from cache is not worth zero, and a zero would read as "no data".
MIN_DATA_QUALITY = 0.1

#: Where the factor lives in `config/sources.yaml`.
CONFIG_SECTION = "degrade"
CONFIG_KEY = "data_quality_degrade_factor"

#: The only cache-max-age literal in the pipeline. `config/sources.yaml` normally supplies
#: the value; this is the fallback used when the key — or the whole section — is absent.
DEFAULT_CACHE_MAX_AGE_HOURS = 24.0

_CONFIG_PATH = f"{CONFIG_SECTION}.{CONFIG_KEY}"


def degrade_factor(
    settings: Settings | None = None,
    *,
    sources: dict[str, Any] | None = None,
) -> float:
    """Return the configured degrade factor.

    Args:
        settings: Settings used to locate `config/sources.yaml`. Defaults to a fresh
            :class:`~pipeline.settings.Settings`, which is what production callers want.
        sources: An already-parsed `sources.yaml` mapping. Callers that hold one (such as
            :class:`~pipeline.providers.base.ProviderRegistry`) pass it to avoid re-reading
            the file; when given, `settings` is ignored.

    Returns:
        The factor, guaranteed to be a real number in the half-open interval (0.0, 1.0].

    Raises:
        ValueError: If the configured value is not a number, or falls outside (0.0, 1.0].
            A factor above 1.0 would *raise* data quality when inputs degrade and a factor
            of 0.0 would erase it entirely; both publish a number that is not true, which
            is the exact failure this config key exists to prevent.
    """
    if sources is None:
        sources = (settings or Settings()).load_sources()

    section = sources.get(CONFIG_SECTION) or {}
    if not isinstance(section, dict):
        raise ValueError(f"{CONFIG_SECTION} must be a mapping in sources.yaml, got {type(section).__name__}")

    raw = section.get(CONFIG_KEY, DEFAULT_DEGRADE_FACTOR)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError(f"{_CONFIG_PATH} must be a number, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{_CONFIG_PATH} must be a number, got {raw!r}") from exc

    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"{_CONFIG_PATH} must be a finite number in (0.0, 1.0], got {value}")
    return value


def cache_max_age_hours(
    settings: Settings | None = None,
    *,
    sources: dict[str, Any] | None = None,
) -> float:
    """Return the configured last-good cache max age in hours (one home, #62 accessor shape, #66).

    ``degrade.cache_max_age_hours`` in ``config/sources.yaml`` was dead config everywhere
    except ``providers/rss_news.py``, which read it independently. Every consumer now resolves
    the cap through this accessor — the key is a fact, not documentation.

    A cap of ``0`` or negative would expire every cache entry immediately; silently defaulting
    past a bad value is how the key became dead in the first place.

    Args:
        settings: Settings used to locate `config/sources.yaml`. Defaults to a fresh
            :class:`~pipeline.settings.Settings`.
        sources: An already-parsed `sources.yaml` mapping. When given, `settings` is ignored.

    Returns:
        The cap in hours, guaranteed to be a positive finite number.

    Raises:
        ValueError: If the configured value is not a number, or is not positive. A cap of
            zero or negative would expire everything, which is never the intent.
    """
    if sources is None:
        sources = (settings or Settings()).load_sources()

    section = sources.get(CONFIG_SECTION) or {}
    if not isinstance(section, dict):
        raise ValueError(f"{CONFIG_SECTION} must be a mapping in sources.yaml, got {type(section).__name__}")

    raw = section.get("cache_max_age_hours", DEFAULT_CACHE_MAX_AGE_HOURS)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError(f"degrade.cache_max_age_hours must be a number, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"degrade.cache_max_age_hours must be a number, got {raw!r}") from exc

    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"degrade.cache_max_age_hours must be a positive finite number, got {value}")
    return value


def degraded_quality(
    degraded_count: int,
    *,
    base: float = 1.0,
    factor: float | None = None,
    floor: float = MIN_DATA_QUALITY,
    digits: int = 3,
    settings: Settings | None = None,
    sources: dict[str, Any] | None = None,
) -> float:
    """Apply the degrade factor once per failed input and clamp the result.

    This is the shared implementation behind every collector's ``_quality()`` and behind
    :func:`pipeline.risk.confidence.quality_factor`.

    Args:
        degraded_count: How many inputs degraded. Zero means a clean run.
        base: Quality before degradation is applied.
        factor: Override the configured factor. Callers that already resolved it — or that
            want to pin one in a test — pass it here; ``None`` reads it from config.
        floor: Lower clamp on the result.
        digits: Decimal places to round to. Collectors publish 3; confidence uses 4.
        settings: Forwarded to :func:`degrade_factor` when `factor` is ``None``.
        sources: Forwarded to :func:`degrade_factor` when `factor` is ``None``.

    Returns:
        ``round(max(floor, base * factor ** degraded_count), digits)``.

    Raises:
        ValueError: If `degraded_count` is negative, or the configured factor is invalid.
    """
    if degraded_count < 0:
        raise ValueError(f"degraded_count must be >= 0, got {degraded_count}")

    resolved = degrade_factor(settings, sources=sources) if factor is None else float(factor)
    return round(max(floor, base * (resolved**degraded_count)), digits)
