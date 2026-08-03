"""Market Regime rule engine (architecture P0-5: rule engine first, modeling deferred to V2).

9 states: goldilocks / risk_on / disinflation / reflation / late_cycle /
stagflation / liquidity_stress / risk_off / crisis.
Rules are based on threshold combinations (VIX/spread/curve/breadth/cross-asset/momentum)
and output the decision basis (explainability).
"""

from __future__ import annotations

from typing import Any


def infer_regime(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Input context (vix/hy_oas/yield_curve/breadth/cross_asset/momentum/dxy),
    returns (regime, evidence_list)."""
    vix = ctx.get("vix")
    hy_oas = ctx.get("hy_oas")
    curve = ctx.get("yield_curve_10y2y")
    breadth = ctx.get("breadth_above_ma200")
    cross = ctx.get("cross_asset_confirmation")
    momentum = ctx.get("momentum_3m")
    dxy = ctx.get("dxy")

    evidence: list[str] = []

    # Crisis / risk-off take priority
    if vix is not None and vix >= 40:
        evidence.append(f"VIX={vix:.1f} ≥ 40")
        return "crisis", evidence
    if hy_oas is not None and hy_oas >= 7.0:
        evidence.append(f"HY OAS={hy_oas:.2f} ≥ 7.0")
        return "crisis", evidence
    if (vix is not None and vix >= 28) or (breadth is not None and breadth <= 0.35):
        if vix is not None:
            evidence.append(f"VIX={vix:.1f} ≥ 28")
        if breadth is not None:
            evidence.append(f"Breadth={breadth:.2f} ≤ 0.35")
        return "risk_off", evidence

    # Liquidity stress
    if hy_oas is not None and hy_oas >= 5.0:
        evidence.append(f"HY OAS={hy_oas:.2f} ≥ 5.0")
        return "liquidity_stress", evidence

    # Stagflation: inverted curve + high-rate pressure + weak momentum
    if curve is not None and curve < 0 and (momentum is not None and momentum < 0):
        evidence.append(f"Yield curve={curve:.2f} < 0 and momentum={momentum:.1f} < 0")
        return "stagflation", evidence

    # Reflation: steepening curve + strong momentum + weakening dollar
    if curve is not None and curve > 0.5 and (momentum is None or momentum > 5):
        evidence.append(f"Yield curve={curve:.2f} > 0.5 and strong momentum")
        return "reflation", evidence

    # Disinflation: inverted curve + weak momentum + neutral vol
    if curve is not None and curve < 0:
        evidence.append(f"Yield curve={curve:.2f} < 0")
        return "disinflation", evidence

    # Late cycle: wide credit but rising vol + cross-asset confirmation leaning risk
    if cross is not None and cross >= 0.55 and (vix is not None and vix >= 18):
        evidence.append(f"Cross-asset={cross:.2f} ≥ 0.55 and VIX={vix:.1f} ≥ 18")
        return "late_cycle", evidence

    # Goldilocks: low vol + positive momentum + healthy breadth
    if (vix is None or vix < 18) and (momentum is None or momentum > 0) and (breadth is None or breadth > 0.5):
        evidence.append("low vol + positive momentum + healthy breadth")
        return "goldilocks", evidence

    # Risk On
    if (vix is not None and vix < 20) or (momentum is not None and momentum > 5):
        evidence.append("low volatility or strong momentum")
        return "risk_on", evidence

    evidence.append("default: late_cycle (no strong signal)")
    return "late_cycle", evidence
