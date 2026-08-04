"""Confidence computation (architecture P0-5: confidence = f(data quality, indicator coverage, signal consistency)).

Product-level definition (not statistically strict): default weights data_quality 0.4 / coverage 0.4 / consistency 0.2.
"""

from __future__ import annotations

import math

from pipeline.degrade import degraded_quality
from pipeline.settings import Settings


def compute_confidence(
    data_quality: float,
    coverage: float,
    consistency: float,
    weights: dict[str, float] | None = None,
) -> float:
    weights = weights or {"data_quality": 0.4, "coverage": 0.4, "consistency": 0.2}
    total_w = sum(weights.values()) or 1.0
    score = (
        weights.get("data_quality", 0) * max(0.0, min(1.0, data_quality))
        + weights.get("coverage", 0) * max(0.0, min(1.0, coverage))
        + weights.get("consistency", 0) * max(0.0, min(1.0, consistency))
    ) / total_w
    return round(max(0.0, min(1.0, score)), 4)


def consistency_from_dimension_scores(scores: list[float]) -> float:
    """Signal consistency: the more dispersed the dimension scores, the lower the consistency. 1 - min(1, std/50)."""
    if len(scores) < 2:
        return 1.0
    mean = sum(scores) / len(scores)
    var = sum((s - mean) ** 2 for s in scores) / len(scores)
    std = math.sqrt(var)
    return round(max(0.0, min(1.0, 1.0 - std / 50.0)), 4)


def quality_factor(
    degraded_count: int,
    base: float = 1.0,
    per_degrade: float | None = None,
    *,
    settings: Settings | None = None,
) -> float:
    """Degrade count → data quality (architecture §1.4).

    The per-degrade factor comes from `config/sources.yaml` (see :mod:`pipeline.degrade`)
    unless `per_degrade` pins one explicitly.
    """
    return degraded_quality(
        degraded_count,
        base=base,
        factor=per_degrade,
        digits=4,
        settings=settings,
    )


#: The only proxy-discount literal in the pipeline (#69 ruling: its own knob, NOT the degrade
#: factor). `config/risk_model.yaml`'s `confidence.proxy_discount_factor` normally supplies
#: the value; this is the fallback. It answers "how much less do we trust an estimate than a
#: measurement" — a different question from the degrade factor's "how much does data_quality
#: drop per failed input", so it is deliberately NOT `pipeline.degrade.degrade_factor`.
DEFAULT_PROXY_DISCOUNT_FACTOR = 0.8


def proxy_discount_factor(
    settings: Settings | None = None,
    *,
    risk_model: dict | None = None,
) -> float:
    """Return the configured proxy discount (#69).

    Read once from `config/risk_model.yaml` under the `confidence` block
    (`confidence.proxy_discount_factor`), range-checked like
    :func:`pipeline.degrade.degrade_factor`. A proxy discount of ``0`` or ``> 1`` is
    nonsense — it would erase or *boost* an estimate's coverage — so it raises rather than
    silently defaulting.

    Args:
        settings: Settings used to locate `config/risk_model.yaml`.
        risk_model: An already-parsed risk_model mapping; when given, `settings` is ignored.

    Returns:
        The discount in (0.0, 1.0].
    """
    if risk_model is None:
        risk_model = (settings or Settings()).load_risk_model()
    confidence_cfg = risk_model.get("confidence", {}) or {}
    if not isinstance(confidence_cfg, dict):
        raise ValueError(f"confidence must be a mapping in risk_model.yaml, got {type(confidence_cfg).__name__}")

    raw = confidence_cfg.get("proxy_discount_factor", DEFAULT_PROXY_DISCOUNT_FACTOR)
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        raise ValueError(f"confidence.proxy_discount_factor must be a number, got {raw!r}")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"confidence.proxy_discount_factor must be a number, got {raw!r}") from exc

    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"confidence.proxy_discount_factor must be a finite number in (0.0, 1.0], got {value}")
    return value
