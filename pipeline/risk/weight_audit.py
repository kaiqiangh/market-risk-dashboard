"""Risk-model weight balance audit (Global Risk Score concentration + scoring-path coverage).

Why this module exists
---------------------
The 6-dimension weights in ``config/risk_model.yaml`` are *configured* intent. Two things
routinely make them untrue in the published score, and neither is visible in ``risk.json``:

1. **Scoring-path coverage.** An indicator only moves the score if it resolves to a scoring
   path — a percentile window (``INDICATOR_HISTORY_SERIES``) or a heuristic rule
   (``HEURISTIC_RULES``). A configured key with neither silently falls back to
   ``fallback_percentile`` (50.0) on every run, i.e. it carries its full weight as a
   *constant*, and the constant's presence still counts as coverage=1.0 in confidence.
   The configured weight therefore overstates the model's responsiveness.
2. **Dynamic concentration.** Even when every indicator is live, a dimension's *configured*
   weight says nothing about how much it moves the total. A 20%-weight dimension whose
   indicators are pinned near their window extremes dominates the day-over-day variance.

This module computes both, from the shipped config and the published risk history. It is
pure computation (no IO): the CLI in ``scripts/risk_weight_audit.py`` supplies the files.

Everything here is descriptive. It proposes nothing and changes no score — rebalancing is a
calibration decision (``config/risk_model.yaml`` ``calibration_policy``), not an audit result.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pipeline.risk.model import INDICATOR_HISTORY_SERIES
from pipeline.risk.scoring import HEURISTIC_RULES

#: Scoring paths an indicator can resolve to, in descending trust order.
SCORING_PATHS = ("percentile", "heuristic", "unmapped")

#: The value an unmapped indicator is scored at on every run (scoring.compute_indicator_score
#: fallback). Named here so the audit can report the *constant point contribution*, not just
#: the dead weight.
UNMAPPED_FALLBACK_SCORE = 50.0

#: A single indicator carrying more than this share of the total score is reported as a
#: concentration risk: one input (often one proxy) can then move the headline number alone.
MAX_SINGLE_INDICATOR_SHARE = 0.10

#: Dimension score standard deviation (in 0-100 points) below which a dimension is reported as
#: non-responsive over the audited window. 0.05 pt is far below any economically meaningful
#: daily move, so it only catches inputs that are effectively pinned.
NON_RESPONSIVE_STD = 0.05


@dataclass(frozen=True)
class IndicatorWeight:
    """One configured indicator resolved to its share of the total score."""

    dimension: str
    key: str
    dimension_weight: float
    indicator_weight: float
    global_weight: float
    scoring_path: str


def scoring_path(key: str) -> str:
    """Resolve one indicator key to its scoring path, or ``unmapped`` when it has none.

    ``unmapped`` is the failure the audit exists to surface: the key is configured (so it
    carries weight) but no rule and no history series will ever score it.
    """
    if INDICATOR_HISTORY_SERIES.get(key) is not None:
        return "percentile"
    if key in HEURISTIC_RULES:
        return "heuristic"
    return "unmapped"


def configured_indicator_weights(risk_model: dict[str, Any]) -> list[IndicatorWeight]:
    """Expand the 2-level config into per-indicator global weights.

    The global weight is ``dimension_weight × indicator_weight / Σ(indicator_weight in that
    dimension)`` — the same normalization ``RiskModel._build_dimensions`` applies, so the
    numbers here are directly comparable with a published ``top_drivers`` contribution.
    """
    dimensions = risk_model.get("dimensions", {}) or {}
    indicators = risk_model.get("indicators", {}) or {}
    out: list[IndicatorWeight] = []
    for dim_key, dim_cfg in dimensions.items():
        items = indicators.get(dim_key, []) or []
        dim_weight = float((dim_cfg or {}).get("weight", 0.0))
        total_indicator_weight = sum(float(item.get("weight", 0.0)) for item in items)
        if total_indicator_weight <= 0:
            continue
        for item in items:
            key = str(item.get("key", ""))
            indicator_weight = float(item.get("weight", 0.0))
            out.append(
                IndicatorWeight(
                    dimension=dim_key,
                    key=key,
                    dimension_weight=dim_weight,
                    indicator_weight=indicator_weight,
                    global_weight=round(dim_weight * indicator_weight / total_indicator_weight, 4),
                    scoring_path=scoring_path(key),
                )
            )
    return out


def weight_concentration(global_weights: Sequence[float]) -> dict[str, float]:
    """Herfindahl-style concentration of a weight vector (normalized to sum 1).

    ``hhi`` is reported on the normalized share vector: 1/N is a perfectly even split, 1.0 is
    a single input carrying everything. ``effective_n`` (=1/hhi) reads as "how many equally
    weighted inputs this vector is worth".
    """
    weights = [float(w) for w in global_weights if float(w) > 0]
    total = sum(weights)
    if total <= 0 or not weights:
        return {
            "hhi": 0.0,
            "equal_hhi": 0.0,
            "effective_n": 0.0,
            "top1_share": 0.0,
            "top3_share": 0.0,
            "max_single_share": 0.0,
        }
    shares = sorted((w / total for w in weights), reverse=True)
    hhi = sum(share * share for share in shares)
    return {
        "hhi": round(hhi, 4),
        "equal_hhi": round(1.0 / len(shares), 4),
        "effective_n": round(1.0 / hhi, 2),
        "top1_share": round(shares[0], 4),
        "top3_share": round(sum(shares[:3]), 4),
        "max_single_share": round(shares[0], 4),
    }


def score_path_coverage(weights: Iterable[IndicatorWeight]) -> dict[str, Any]:
    """Aggregate configured global weight by scoring path.

    ``dead_weight`` is the share of the total score that is a constant
    (``unmapped_fallback_score``) on every run, and ``dead_points`` is the fixed number of
    points it contributes to the 0-100 headline.
    """
    by_path: dict[str, dict[str, float]] = {
        path: {"count": 0, "global_weight": 0.0} for path in SCORING_PATHS
    }
    unmapped_keys: list[str] = []
    for item in weights:
        bucket = by_path[item.scoring_path]
        bucket["count"] += 1
        bucket["global_weight"] = round(bucket["global_weight"] + item.global_weight, 4)
        if item.scoring_path == "unmapped":
            unmapped_keys.append(item.key)
    total = round(sum(item.global_weight for item in weights), 2)
    dead_weight = round(by_path["unmapped"]["global_weight"], 2)
    return {
        "by_path": by_path,
        "total_global_weight": total,
        "unmapped_keys": sorted(unmapped_keys),
        "dead_weight": dead_weight,
        "dead_points": round(dead_weight * UNMAPPED_FALLBACK_SCORE / 100.0, 4),
    }

def dimension_stats(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-dimension descriptive statistics over the published risk history.

    ``unique`` counts distinct scores: a dimension with one distinct value is not responding to
    the market at all, whatever its configured weight says.
    """
    if not rows:
        return []
    keys = sorted({key for row in rows for key in (row.get("dim_scores") or {})})
    out: list[dict[str, Any]] = []
    for key in keys:
        values = [
            float(row["dim_scores"][key])
            for row in rows
            if isinstance((row.get("dim_scores") or {}).get(key), (int, float))
        ]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        out.append(
            {
                "key": key,
                "observations": len(values),
                "mean": round(mean, 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "std": round(math.sqrt(variance), 4),
                "range": round(max(values) - min(values), 4),
                "unique": len({round(value, 4) for value in values}),
                "non_responsive": math.sqrt(variance) < NON_RESPONSIVE_STD,
            }
        )
    return out


def variance_decomposition(
    rows: Sequence[dict[str, Any]], risk_model: dict[str, Any]
) -> dict[str, Any]:
    """Decompose the total score's time-series variance into per-dimension contributions.

    Uses the identity ``total ≈ Σ (dimension_weight/100) × dimension_score`` (the
    un-renormalized form) and attributes ``Cov(contribution_d, total) / Var(total)`` to each
    dimension. Shares sum to ~1 and can be negative — a negative share means the dimension
    moved *against* the total, i.e. it diversified rather than drove.

    ``residual_mean_abs`` / ``residual_max_abs`` are reported rather than hidden: they are
    non-zero on days where a dimension was missing and the model redistributed its weight,
    which the fixed-weight reconstruction cannot express. A large *max* means the configured
    weights were materially not what was applied on at least one day.
    """
    # Dimension weights come straight from the config: the decomposition needs the *level*
    # weights, which exist even for a model whose indicator table is empty.
    weights = {
        str(key): float((cfg or {}).get("weight", 0.0))
        for key, cfg in (risk_model.get("dimensions", {}) or {}).items()
    }
    totals = [float(row["total_score"]) for row in rows if isinstance(row.get("total_score"), (int, float))]
    if len(totals) < 2 or not weights:
        return {
            "dimensions": [],
            "residual_mean_abs": None,
            "residual_max_abs": None,
            "observations": len(totals),
        }

    usable_rows = [row for row in rows if isinstance(row.get("total_score"), (int, float))]
    mean_total = sum(totals) / len(totals)
    variance_total = sum((value - mean_total) ** 2 for value in totals) / len(totals)
    if variance_total <= 0:
        return {
            "dimensions": [
                {"key": key, "mean_contribution": None, "variance_share": None, "std": None}
                for key in sorted(weights)
            ],
            "residual_mean_abs": 0.0,
            "residual_max_abs": 0.0,
            "observations": len(totals),
            "note": "total score did not vary over the audited window",
        }

    residual = 0.0
    residual_max = 0.0
    per_dimension: list[dict[str, Any]] = []
    for key in sorted(weights):
        contributions = [
            weights[key] / 100.0 * float(row["dim_scores"][key])
            for row in usable_rows
            if isinstance((row.get("dim_scores") or {}).get(key), (int, float))
        ]
        if len(contributions) != len(totals):
            per_dimension.append(
                {"key": key, "mean_contribution": None, "variance_share": None, "std": None}
            )
            continue
        mean_contribution = sum(contributions) / len(contributions)
        covariance = (
            sum(
                (contributions[i] - mean_contribution) * (totals[i] - mean_total)
                for i in range(len(totals))
            )
            / len(totals)
        )
        std = math.sqrt(
            sum((value - mean_contribution) ** 2 for value in contributions) / len(contributions)
        )
        per_dimension.append(
            {
                "key": key,
                "configured_weight": weights[key],
                "mean_contribution": round(mean_contribution, 4),
                "variance_share": round(covariance / variance_total, 4),
                "std": round(std, 4),
            }
        )
    for row, total in zip(usable_rows, totals, strict=False):
        deviation = abs(
            sum(
                weights[key] / 100.0 * float(row["dim_scores"][key])
                for key in weights
                if isinstance((row.get("dim_scores") or {}).get(key), (int, float))
            )
            - total
        )
        residual += deviation
        residual_max = max(residual_max, deviation)
    return {
        "dimensions": sorted(
            per_dimension,
            key=lambda item: (item["variance_share"] is None, -(item["variance_share"] or 0.0)),
        ),
        "residual_mean_abs": round(residual / len(totals), 4),
        "residual_max_abs": round(residual_max, 4),
        "observations": len(totals),
    }


def audit(risk_model: dict[str, Any], history_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Run the full balance audit and return a serializable report.

    ``findings`` is the reviewable output: each entry names an imbalance and its evidence, so a
    reader does not have to re-derive it. The audit never mutates the model or a score.
    """
    weights = configured_indicator_weights(risk_model)
    coverage = score_path_coverage(weights)
    concentration = weight_concentration([item.global_weight for item in weights])
    dimensions = dimension_stats(history_rows)
    decomposition = variance_decomposition(history_rows, risk_model)

    over_cap = [
        {"key": item.key, "dimension": item.dimension, "global_weight": item.global_weight}
        for item in weights
        if item.global_weight > MAX_SINGLE_INDICATOR_SHARE * 100.0
    ]
    single_indicator_dimensions = [
        {
            "key": key,
            "indicator": items[0].key,
            "global_weight": items[0].global_weight,
        }
        for key, items in _group_by_dimension(weights).items()
        if len(items) == 1
    ]
    non_responsive = [item for item in dimensions if item["non_responsive"]]

    findings: list[dict[str, Any]] = []
    if coverage["dead_weight"] > 0:
        findings.append(
            {
                "code": "unmapped_indicators",
                "severity": "high",
                "detail": (
                    f"{len(coverage['unmapped_keys'])} configured indicator(s) resolve to no scoring path "
                    f"and are scored at the constant fallback {UNMAPPED_FALLBACK_SCORE} on every run"
                ),
                "weight_share": round(coverage["dead_weight"] / 100.0, 4),
                "fixed_points": coverage["dead_points"],
                "evidence": coverage["unmapped_keys"],
            }
        )
    if over_cap:
        findings.append(
            {
                "code": "single_indicator_over_cap",
                "severity": "high",
                "detail": (
                    f"indicator(s) exceed the {MAX_SINGLE_INDICATOR_SHARE:.0%} single-input share cap"
                ),
                "evidence": over_cap,
            }
        )
    for item in single_indicator_dimensions:
        findings.append(
            {
                "code": "single_indicator_dimension",
                "severity": "medium",
                "detail": (
                    f"dimension {item['key']!r} is backed by one indicator ({item['indicator']}), "
                    f"so it has no internal diversification"
                ),
                "evidence": item,
            }
        )
    for item in non_responsive:
        findings.append(
            {
                "code": "non_responsive_dimension",
                "severity": "medium",
                "detail": (
                    f"dimension {item['key']!r} scored one value in all {item['observations']} "
                    f"observations (std {item['std']})"
                ),
                "evidence": item,
            }
        )
    for item in decomposition.get("dimensions", []):
        share = item.get("variance_share")
        configured = item.get("configured_weight")
        if share is None or configured is None:
            continue
        if share > 2 * configured / 100.0 and share > 0.25:
            findings.append(
                {
                    "code": "variance_over_concentration",
                    "severity": "high",
                    "detail": (
                        f"dimension {item['key']!r} explains {share:.1%} of the total score's "
                        f"variance on a configured weight of {configured:g}%"
                    ),
                    "evidence": item,
                }
            )

    return {
        "indicator_weights": [item.__dict__ for item in weights],
        "concentration": concentration,
        "score_path_coverage": coverage,
        "dimension_stats": dimensions,
        "variance_decomposition": decomposition,
        "findings": findings,
        "thresholds": {
            "max_single_indicator_share": MAX_SINGLE_INDICATOR_SHARE,
            "non_responsive_std": NON_RESPONSIVE_STD,
        },
    }


def blocking_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings that must fail a check: an input that cannot be scored at all."""
    return [item for item in report.get("findings", []) if item["code"] == "unmapped_indicators"]


def render(report: dict[str, Any]) -> str:
    """Render an audit report as a plain-text table for a terminal or CI log."""
    lines: list[str] = ["Risk model weight audit", "=" * 78]
    weights = sorted(report["indicator_weights"], key=lambda item: -item["global_weight"])
    lines.append(f"{'dimension':17s} {'indicator':26s} {'globalW':>8s}  path")
    for item in weights:
        flag = "  <-- unmapped" if item["scoring_path"] == "unmapped" else ""
        lines.append(
            f"{item['dimension']:17s} {item['key']:26s} {item['global_weight']:8.3f}  "
            f"{item['scoring_path']}{flag}"
        )

    concentration = report["concentration"]
    coverage = report["score_path_coverage"]
    lines += [
        "",
        f"concentration: hhi={concentration['hhi']:.4f} (even={concentration['equal_hhi']:.4f}) "
        f"effective_n={concentration['effective_n']:.1f} "
        f"top1={concentration['top1_share']:.1%} top3={concentration['top3_share']:.1%}",
        "scoring paths: " + ", ".join(
            f"{path}={coverage['by_path'][path]['count']}"
            f"({coverage['by_path'][path]['global_weight']:.2f}w)"
            for path in SCORING_PATHS
        ),
    ]
    if coverage["dead_weight"] > 0:
        lines.append(
            f"dead weight: {coverage['dead_weight']:.2f} of 100 points is a constant "
            f"({coverage['dead_points']:+.2f} pts every run)"
        )

    if report["dimension_stats"]:
        lines += ["", f"{'dimension':18s} {'mean':>7s} {'min':>7s} {'max':>7s} {'std':>7s} {'uniq':>5s}"]
        for item in report["dimension_stats"]:
            lines.append(
                f"{item['key']:18s} {item['mean']:7.2f} {item['min']:7.2f} {item['max']:7.2f} "
                f"{item['std']:7.2f} {item['unique']:5d}"
            )

    decomposition = report["variance_decomposition"]
    if decomposition.get("dimensions"):
        lines += ["", f"{'dimension':18s} {'configured':>10s} {'meanContrib':>12s} {'varShare':>9s}"]
        for item in decomposition["dimensions"]:
            share = item["variance_share"]
            lines.append(
                f"{item['key']:18s} {str(item.get('configured_weight')):>10s} "
                f"{str(item['mean_contribution']):>12s} "
                f"{('n/a' if share is None else f'{share:9.1%}')}"
            )
        lines.append(
            f"reconstruction residual (mean |Σw·score − total|) = {decomposition['residual_mean_abs']}"
            f" (max {decomposition.get('residual_max_abs')})"
        )

    if report["findings"]:
        lines += ["", f"findings ({len(report['findings'])}):"]
        for item in report["findings"]:
            lines.append(f"  [{item['severity']:6s}] {item['code']}: {item['detail']}")
    else:
        lines += ["", "findings: none"]
    return "\n".join(lines)


def _group_by_dimension(weights: Iterable[IndicatorWeight]) -> dict[str, list[IndicatorWeight]]:
    grouped: dict[str, list[IndicatorWeight]] = {}
    for item in weights:
        grouped.setdefault(item.dimension, []).append(item)
    return grouped
