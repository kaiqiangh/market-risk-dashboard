"""Confidence computation (architecture P0-5: confidence = f(data quality, indicator coverage, signal consistency)).

Product-level definition (not statistically strict): default weights data_quality 0.4 / coverage 0.4 / consistency 0.2.
"""

from __future__ import annotations

import math


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


def quality_factor(degraded_count: int, base: float = 1.0, per_degrade: float = 0.8) -> float:
    """Degrade count → data quality (×0.8 per degrade, architecture §1.4)."""
    factor = base * (per_degrade ** degraded_count)
    return round(max(0.1, factor), 4)
