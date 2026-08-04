"""6-dimension risk model (architecture §3.2/§1.8 calibration red lines + Fix rounds P0-2/P2-11).

- The risk score is a "modeled market stress estimate", not an exact crash probability
  (fixed disclaimer copy).
- Weights come from config/risk_model.yaml; when a dimension has coverage=0, weights are
  renormalized proportionally across the remaining dimensions.
- Sub-indicator scoring primary path (P0-2): 5Y historical percentile window
  (config.percentile_window_years); the heuristic table is only the fallback for insufficient
  history; percentile/z_score are computed whenever history allows.
- Dimension trend (P2-11): computed by comparing each dimension's score to the previous day;
  trend_1w/trend_1m are computed from the risk history series (when history is sufficient).
- Outputs RiskModelResult (pydantic contract, score 0-100 / confidence 0-1).
"""

from __future__ import annotations

from typing import Any

from pipeline.risk import confidence as conf_mod
from pipeline.risk import regime as regime_mod
from pipeline.risk.scoring import compute_indicator_score
from pipeline.schemas import (
    DriverContribution,
    RiskDimension,
    RiskIndicator,
    RiskLevel,
    RiskModelResult,
)
from pipeline.settings import Settings
from pipeline.utils import now_utc

DIMENSION_LABELS = {
    "macro": "Macro",
    "liquidity_credit": "Liquidity & Credit",
    "equity_structure": "Equity Structure",
    "volatility": "Volatility",
    "cross_asset": "Cross Asset",
    "trend": "Trend",
}

DEFAULT_DISCLAIMER = "This indicator is a modeled estimate of market stress based on historical data and current market signals. It is not a definitive probability or investment advice."

# Indicator key → 5Y history series source (FRED series key; tuple means a composite series, e.g. term spread)
INDICATOR_HISTORY_SERIES: dict[str, str | tuple[str, str]] = {
    "real_rate_dfii10": "dfii10",
    "yield_curve_10y2y": ("dgs10", "dgs2"),
    "hy_oas": "bamlh0a0hym2",
    "ig_oas": "bamlc0a0cm",
    "dollar_index": "dtwexbgs",
    "dgs10": "dgs10",
    "fed_balance_sheet": "walcl",
    "reverse_repo": "rrpontsyd",
    "vix": "vixcls",
    "realized_vol": None,  # computed: no independent 5Y series (heuristic fallback)
}


def _ind(
    key: str,
    label: str,
    value: float | None,
    direction: str,
    source: str,
    weight: float,
    history: list[float] | None = None,
    fallback: float = 50.0,
    is_proxy: bool = False,
) -> RiskIndicator:
    score, pct, z = compute_indicator_score(key, value, history, direction, fallback=fallback)
    return RiskIndicator(
        key=key, label=label, value=value,
        percentile=pct, z_score=z,
        risk_score=score,
        direction=direction, weight=weight, source=source,
        updated_at=None, status="fresh" if value is not None else "missing",
        is_proxy=is_proxy,
    )


class RiskModel:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        raw = self.settings.load_risk_model()
        self.model_version = str(raw.get("model_version", "1.0.0"))
        self.dim_cfg: dict[str, dict[str, float]] = raw.get("dimensions", {})
        thresholds = raw.get("thresholds", {}).get("risk_level", {})
        self.thresholds = _parse_thresholds(thresholds)
        cw = raw.get("confidence", {}).get("weights", {})
        self.conf_weights = {k: float(v) for k, v in cw.items()}
        scoring_cfg = raw.get("scoring", {})
        self.percentile_window_years = int(scoring_cfg.get("percentile_window_years", 5))
        self.fallback_percentile = float(scoring_cfg.get("fallback_percentile", 50.0))
        # 5Y window ≈ 252 trading days/year (daily-frequency series)
        self._max_history_samples = max(60, self.percentile_window_years * 252)

    # ---- 5Y history window ----

    def _series_values(self, ctx: dict[str, Any], series_key: str) -> list[float]:
        """Extract the 5Y-window values of a series from series_history (ascending, latest last)."""
        series_history = ctx.get("series_history", {}) or {}
        rows = series_history.get(series_key) or []
        values = [
            float(r["value"])
            for r in rows
            if isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)
        ]
        return values[-self._max_history_samples:]

    def _indicator_history(self, ctx: dict[str, Any], key: str) -> list[float] | None:
        """Indicator key → 5Y history values (composite series aligned by date and differenced; None when no source)."""
        spec = INDICATOR_HISTORY_SERIES.get(key)
        if spec is None:
            return None
        if isinstance(spec, str):
            values = self._series_values(ctx, spec)
            return values if values else None

        # Composite series: e.g. 10Y-2Y term spread = DGS10 - DGS2 (aligned by date)
        series_history = ctx.get("series_history", {}) or {}
        maps: list[dict[str, float]] = []
        for series_key in spec:
            rows = series_history.get(series_key) or []
            maps.append(
                {
                    str(r.get("date", "")): float(r["value"])
                    for r in rows
                    if isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)
                }
            )
        if len(maps) < 2 or not maps[0] or not maps[1]:
            return None
        common = sorted(set(maps[0]) & set(maps[1]))
        diffs = [round(maps[0][d] - maps[1][d], 6) for d in common]
        return diffs[-self._max_history_samples:] if diffs else None

    # ---- Per-dimension indicators ----

    def _macro_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        macro = ctx.get("macro")
        rates = {m.key: m for m in getattr(macro, "rates", [])}
        dgs10 = rates.get("dgs10")
        dfii10 = rates.get("dfii10")
        dgs2 = rates.get("dgs2")
        curve = (dgs10.value - dgs2.value) if (dgs10 and dgs2 and dgs10.value is not None and dgs2.value is not None) else None
        dollar = next((m for m in getattr(macro, "fx", []) if m.key == "dtwexbgs"), None)
        return [
            _ind("real_rate_dfii10", "10Y Real Rate", dfii10.value if dfii10 else None, "higher_is_riskier", "FRED", 5.0,
                 history=self._indicator_history(ctx, "real_rate_dfii10")),
            _ind("yield_curve_10y2y", "10Y-2Y Curve", curve, "lower_is_riskier", "FRED", 5.0,
                 history=self._indicator_history(ctx, "yield_curve_10y2y")),
            _ind("dollar_index", "Dollar Index", dollar.value if dollar else None, "higher_is_riskier", "FRED", 5.0,
                 history=self._indicator_history(ctx, "dollar_index")),
            _ind("dgs10", "10Y Yield", dgs10.value if dgs10 else None, "neutral", "FRED", 5.0,
                 history=self._indicator_history(ctx, "dgs10")),
        ]

    def _liquidity_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        macro = ctx.get("macro")
        liquidity = {m.key: m for m in getattr(macro, "liquidity", [])}
        w = liquidity.get("walcl")
        rr = liquidity.get("rrpontsyd")
        return [
            _ind("fed_balance_sheet", "Fed Balance Sheet", w.value if w else None, "neutral", "FRED", 5.0,
                 history=self._indicator_history(ctx, "fed_balance_sheet")),
            _ind("reverse_repo", "Reverse Repo", rr.value if rr else None, "neutral", "FRED", 5.0,
                 history=self._indicator_history(ctx, "reverse_repo")),
            _ind("hy_oas", "HY OAS", _first_value(ctx, "credit", "bamlh0a0hym2"), "higher_is_riskier", "FRED", 10.0,
                 history=self._indicator_history(ctx, "hy_oas")),
            _ind("ig_oas", "IG OAS", _first_value(ctx, "credit", "bamlc0a0cm"), "higher_is_riskier", "FRED", 5.0,
                 history=self._indicator_history(ctx, "ig_oas")),
        ]

    def _equity_structure_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        breadth = ctx.get("breadth", {})
        return [
            _ind("breadth_above_ma200", "Breadth > MA200", breadth.get("breadth_above_ma200"), "lower_is_riskier", "computed", 7.0, is_proxy=True),
            _ind("new_highs_ratio", "New Highs Ratio", breadth.get("new_highs_ratio"), "lower_is_riskier", "computed", 4.0, is_proxy=True),
            _ind("new_lows_ratio", "New Lows Ratio", breadth.get("new_lows_ratio"), "higher_is_riskier", "computed", 4.0, is_proxy=True),
            _ind("small_cap_relative", "Small Cap Rel", breadth.get("small_cap_relative"), "lower_is_riskier", "computed", 4.0, is_proxy=True),
            _ind("semis_relative", "Semis Rel", breadth.get("semis_relative"), "lower_is_riskier", "computed", 4.0, is_proxy=True),
        ]

    def _volatility_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        vix = _series_value(ctx, "vixcls")
        return [
            _ind("vix", "VIX", vix, "higher_is_riskier", "FRED", 8.0,
                 history=self._indicator_history(ctx, "vix")),
            _ind("realized_vol", "Realized Vol", ctx.get("trend", {}).get("realized_vol"), "higher_is_riskier", "computed", 7.0),
        ]

    def _cross_asset_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        # 9-signal confirmation hit rate (MVP simplified): cross-asset risk confirmation
        cross = ctx.get("cross_asset", {})
        return [
            _ind("cross_asset_confirmation", "Cross-asset Confirmation", cross.get("confirmation"), "higher_is_riskier", "computed", 15.0, is_proxy=True),
        ]

    def _trend_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        trend = ctx.get("trend", {})
        return [
            _ind("price_vs_ma200", "Price vs MA200", trend.get("price_vs_ma200"), "lower_is_riskier", "computed", 3.0),
            _ind("drawdown_52w", "52W Drawdown", trend.get("drawdown_52w"), "lower_is_riskier", "computed", 3.0),
            _ind("momentum_3m", "3M Momentum", trend.get("momentum_3m"), "lower_is_riskier", "computed", 4.0),
        ]

    # ---- Main flow ----

    def score(self, ctx: dict[str, Any]) -> RiskModelResult:
        builders = {
            "macro": self._macro_indicators,
            "liquidity_credit": self._liquidity_indicators,
            "equity_structure": self._equity_structure_indicators,
            "volatility": self._volatility_indicators,
            "cross_asset": self._cross_asset_indicators,
            "trend": self._trend_indicators,
        }

        prev_dim_scores: dict[str, float] = ctx.get("_prev_dim_scores") or {}
        dimensions: list[RiskDimension] = []
        for dim_key, builder in builders.items():
            indicators = builder(ctx)
            available = [i for i in indicators if i.value is not None]
            coverage = round(len(available) / len(indicators), 4) if indicators else 0.0
            if available:
                dim_score = round(sum(i.risk_score * i.weight for i in available) / sum(i.weight for i in available), 2)
            else:
                dim_score = 0.0
            cfg_weight = float(self.dim_cfg.get(dim_key, {}).get("weight", 0))
            dimensions.append(
                RiskDimension(
                    key=dim_key,
                    label=DIMENSION_LABELS.get(dim_key, dim_key),
                    weight=cfg_weight,
                    effective_weight=cfg_weight,
                    score=dim_score,
                    indicators=indicators,
                    coverage=coverage,
                    trend=_dim_trend(dim_score, prev_dim_scores.get(dim_key)),
                )
            )

        # Renormalization: weights of dimensions with coverage=0 are redistributed proportionally
        # across the remaining dimensions
        total_weight = sum(d.weight for d in dimensions if d.coverage > 0)
        if total_weight <= 0:
            total_weight = sum(d.weight for d in dimensions) or 1.0
        for d in dimensions:
            if d.coverage > 0:
                d.effective_weight = round(d.weight, 4)
            else:
                d.effective_weight = 0.0
        # Redistribute the missing-dimension weight proportionally across valid dimensions
        missing_weight = sum(d.weight for d in dimensions if d.coverage == 0)
        if missing_weight > 0 and total_weight > 0:
            for d in dimensions:
                if d.coverage > 0:
                    d.effective_weight = round(d.weight + d.weight / total_weight * missing_weight, 4)

        denom = sum(d.effective_weight for d in dimensions) or 1.0
        total_score = round(sum(d.effective_weight * d.score for d in dimensions) / denom, 2)

        # Risk level
        risk_level = self._level_for(total_score)

        # Top drivers (#68): an indicator's contribution reflects its OWN share of weight
        # within its dimension, not the dimension's weight. For indicator i in dimension d:
        #   contribution = (d.effective_weight / W) * (i.weight / V_d) * i.risk_score
        # where W = total effective weight and V_d = sum of available indicator weights in d.
        # Summing over every indicator reconciles exactly with the composite score.
        drivers: list[DriverContribution] = []
        for d in dimensions:
            available = [i for i in d.indicators if i.value is not None]
            dim_weight_sum = sum(i.weight for i in available) or 1.0
            for ind in available:
                contribution = round(
                    d.effective_weight / denom * (ind.weight / dim_weight_sum) * ind.risk_score, 4
                )
                drivers.append(
                    DriverContribution(
                        dimension_key=d.key,
                        indicator_key=ind.key,
                        label=ind.label,
                        contribution=contribution,
                        change_1d=None,
                        evidence_ref=None,
                    )
                )
        drivers.sort(key=lambda x: x.contribution, reverse=True)
        top_drivers = drivers[:5]

        # Regime
        regime_ctx = {
            "vix": _series_value(ctx, "vixcls"),
            "hy_oas": _first_value(ctx, "credit", "bamlh0a0hym2"),
            "yield_curve_10y2y": _curve_value(ctx),
            "breadth_above_ma200": ctx.get("breadth", {}).get("breadth_above_ma200"),
            "cross_asset_confirmation": ctx.get("cross_asset", {}).get("confirmation"),
            "momentum_3m": ctx.get("trend", {}).get("momentum_3m"),
            "dollar_index": _first_value(ctx, "fx", "dtwexbgs"),
        }
        regime, regime_evidence = regime_mod.infer_regime(regime_ctx)

        # Trend: compare with the most recent risk history (run.py injects prev_total_score + risk_history)
        prev_score = ctx.get("_prev_total_score")
        trend_1d = round(total_score - prev_score, 2) if prev_score is not None else None
        trend_1w, trend_1m = _history_trends(total_score, ctx.get("_risk_history"))

        # Confidence
        data_quality = float(ctx.get("data_quality", 1.0))
        coverage = sum(d.coverage * d.weight for d in dimensions) / (sum(d.weight for d in dimensions) or 1.0)
        consistency = conf_mod.consistency_from_dimension_scores([d.score for d in dimensions])
        confidence = conf_mod.compute_confidence(data_quality, coverage, consistency, self.conf_weights)

        return RiskModelResult(
            model_version=self.model_version,
            generated_at=now_utc(),
            total_score=total_score,
            risk_level=risk_level,
            trend_1d=trend_1d,
            trend_1w=trend_1w,
            trend_1m=trend_1m,
            dimensions=dimensions,
            top_drivers=top_drivers,
            regime=regime,
            regime_evidence=regime_evidence,
            confidence=confidence,
            confidence_factors={
                "data_quality": round(data_quality, 4),
                "coverage": round(coverage, 4),
                "consistency": consistency,
            },
            disclaimer=DEFAULT_DISCLAIMER,
        )

    def _level_for(self, total_score: float) -> RiskLevel:
        for level, rule in self.thresholds:
            if rule(total_score):
                return level
        return "caution"


def _dim_trend(score: float, prev_score: float | None) -> str:
    """Dimension trend (P2-11): compare with the previous day's score; no previous day → flat."""
    if prev_score is None:
        return "flat"
    if abs(score - prev_score) < 0.01:
        return "flat"
    return "rising" if score > prev_score else "falling"


def _history_trends(total_score: float, rows: Any) -> tuple[float | None, float | None]:
    """trend_1w / trend_1m: computed from the risk history series (None when history is insufficient).

    rows are the prior rows of history/risk/daily.json (excluding today); 1w ≈ 5 trading days, 1m ≈ 21.
    """
    if not rows or not isinstance(rows, list):
        return None, None
    try:
        last_score = float(rows[-1]["total_score"])
        trend_1w = round(total_score - last_score, 2)
    except (KeyError, TypeError, ValueError, IndexError):
        trend_1w = None
    if len(rows) >= 6:
        try:
            week_ago = float(rows[-6]["total_score"])
            trend_1w = round(total_score - week_ago, 2)
        except (KeyError, TypeError, ValueError, IndexError):
            trend_1w = None
    trend_1m = None
    if len(rows) >= 22:
        try:
            month_ago = float(rows[-22]["total_score"])
            trend_1m = round(total_score - month_ago, 2)
        except (KeyError, TypeError, ValueError, IndexError):
            trend_1m = None
    return trend_1w, trend_1m


def _parse_thresholds(raw: dict[str, Any]) -> list[tuple[RiskLevel, Any]]:
    """Build (level, predicate) from config thresholds."""
    out: list[tuple[RiskLevel, Any]] = []
    for level, rule in raw.items():
        if not isinstance(rule, dict):
            continue
        if "lt" in rule and "gte" not in rule:
            out.append((level, lambda s, r=rule: s < float(r["lt"])))
        elif "gte" in rule and "lt" in rule:
            out.append((level, lambda s, r=rule: float(r["gte"]) <= s < float(r["lt"])))
        elif "gte" in rule:
            out.append((level, lambda s, r=rule: s >= float(r["gte"])))
    # Sort by (lower bound) so the first hit takes priority
    return out


def _series_value(ctx: dict[str, Any], key: str) -> float | None:
    macro = ctx.get("macro")
    for group in ("rates", "credit", "inflation", "labor", "liquidity", "fx"):
        for m in getattr(macro, group, []):
            if m.key == key:
                return m.value
    return None


def _first_value(ctx: dict[str, Any], group: str, key: str) -> float | None:
    macro = ctx.get("macro")
    for m in getattr(macro, group, []):
        if m.key == key:
            return m.value
    return None


def _curve_value(ctx: dict[str, Any]) -> float | None:
    macro = ctx.get("macro")
    rates = {m.key: m for m in getattr(macro, "rates", [])}
    dgs10 = rates.get("dgs10")
    dgs2 = rates.get("dgs2")
    if dgs10 and dgs2 and dgs10.value is not None and dgs2.value is not None:
        return round(dgs10.value - dgs2.value, 4)
    return None
