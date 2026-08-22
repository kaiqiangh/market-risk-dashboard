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

from pipeline.degrade import degrade_factor
from pipeline.risk import confidence as conf_mod
from pipeline.risk import regime as regime_mod
from pipeline.risk.scoring import compute_indicator_score
from pipeline.schemas import (
    BreadthSnapshot,
    CrossAssetSignal,
    DriverContribution,
    RiskCalibrationStatus,
    RiskDimension,
    RiskEvidenceState,
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

# Series keys with a canonical macro group must not be accepted from a legacy or incorrect
# group. This prevents a fixture or stale payload from hiding a collection-to-risk wiring bug.
CANONICAL_MACRO_GROUPS = {
    "vixcls": "volatility",
}

DEFAULT_DISCLAIMER = "This indicator is a modeled estimate of market stress based on historical data and current market signals. Data trust is not statistical confidence, a calibrated probability, or investment advice."

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
        self.indicator_cfg: dict[str, list[dict[str, Any]]] = raw.get("indicators", {})
        thresholds = raw.get("thresholds", {}).get("risk_level", {})
        self.thresholds = _parse_thresholds(thresholds)
        cw = raw.get("confidence", {}).get("weights", {})
        self.conf_weights = {k: float(v) for k, v in cw.items()}
        scoring_cfg = raw.get("scoring", {})
        self.percentile_window_years = int(scoring_cfg.get("percentile_window_years", 5))
        self.fallback_percentile = float(scoring_cfg.get("fallback_percentile", 50.0))
        evidence_cfg = raw.get("evidence", {})
        self.insufficient_evidence_threshold = float(
            evidence_cfg.get("insufficient_coverage_threshold", 0.5)
        )
        if not 0.0 <= self.insufficient_evidence_threshold <= 1.0:
            raise ValueError("risk evidence insufficient_coverage_threshold must be between 0 and 1")
        calibration_cfg = raw.get("calibration_policy", {}) or {}
        if not isinstance(calibration_cfg, dict):
            raise ValueError("risk calibration_policy must be a mapping")
        self.calibration_policy_version = str(calibration_cfg.get("version", "1.0.0"))
        calibration_status = str(calibration_cfg.get("status", "provisional"))
        if calibration_status not in {"provisional", "calibrated"}:
            raise ValueError("risk calibration_policy.status must be provisional or calibrated")
        self.calibration_status: RiskCalibrationStatus = calibration_status
        # 5Y window ≈ 252 trading days/year (daily-frequency series)
        self._max_history_samples = max(60, self.percentile_window_years * 252)

    def _indicator_weight(self, dimension: str, key: str) -> float:
        """Read an indicator weight from config; code must not carry a second weight table."""
        for item in self.indicator_cfg.get(dimension, []):
            if item.get("key") == key:
                return float(item["weight"])
        raise ValueError(f"risk_model.yaml: missing weight for {dimension}.{key}")

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
            _ind("real_rate_dfii10", "10Y Real Rate", dfii10.value if dfii10 else None, "higher_is_riskier", "FRED", self._indicator_weight("macro", "real_rate_dfii10"),
                 history=self._indicator_history(ctx, "real_rate_dfii10")),
            _ind("yield_curve_10y2y", "10Y-2Y Curve", curve, "lower_is_riskier", "FRED", self._indicator_weight("macro", "yield_curve_10y2y"),
                 history=self._indicator_history(ctx, "yield_curve_10y2y")),
            _ind("dollar_index", "Dollar Index", dollar.value if dollar else None, "higher_is_riskier", "FRED", self._indicator_weight("macro", "dollar_index"),
                 history=self._indicator_history(ctx, "dollar_index")),
            _ind("dgs10", "10Y Yield", dgs10.value if dgs10 else None, "neutral", "FRED", self._indicator_weight("macro", "dgs10"),
                 history=self._indicator_history(ctx, "dgs10")),
        ]

    def _liquidity_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        macro = ctx.get("macro")
        liquidity = {m.key: m for m in getattr(macro, "liquidity", [])}
        w = liquidity.get("walcl")
        rr = liquidity.get("rrpontsyd")
        return [
            _ind("fed_balance_sheet", "Fed Balance Sheet", w.value if w else None, "neutral", "FRED", self._indicator_weight("liquidity_credit", "fed_balance_sheet"),
                 history=self._indicator_history(ctx, "fed_balance_sheet")),
            _ind("reverse_repo", "Reverse Repo", rr.value if rr else None, "neutral", "FRED", self._indicator_weight("liquidity_credit", "reverse_repo"),
                 history=self._indicator_history(ctx, "reverse_repo")),
            _ind("hy_oas", "HY OAS", _first_value(ctx, "credit", "bamlh0a0hym2"), "higher_is_riskier", "FRED", self._indicator_weight("liquidity_credit", "hy_oas"),
                 history=self._indicator_history(ctx, "hy_oas")),
            _ind("ig_oas", "IG OAS", _first_value(ctx, "credit", "bamlc0a0cm"), "higher_is_riskier", "FRED", self._indicator_weight("liquidity_credit", "ig_oas"),
                 history=self._indicator_history(ctx, "ig_oas")),
        ]

    def _equity_structure_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        breadth = ctx.get("breadth", {})
        return [
            _ind("breadth_above_ma200", "Breadth > MA200", breadth.get("breadth_above_ma200"), "lower_is_riskier", "computed", self._indicator_weight("equity_structure", "breadth_above_ma200"), is_proxy=True),
            _ind("new_highs_ratio", "New Highs Ratio", breadth.get("new_highs_ratio"), "lower_is_riskier", "computed", self._indicator_weight("equity_structure", "new_highs_ratio"), is_proxy=True),
            _ind("new_lows_ratio", "New Lows Ratio", breadth.get("new_lows_ratio"), "higher_is_riskier", "computed", self._indicator_weight("equity_structure", "new_lows_ratio"), is_proxy=True),
            _ind("small_cap_relative", "Small Cap Rel", breadth.get("small_cap_relative"), "lower_is_riskier", "computed", self._indicator_weight("equity_structure", "small_cap_relative"), is_proxy=True),
            _ind("semis_relative", "Semis Rel", breadth.get("semis_relative"), "lower_is_riskier", "computed", self._indicator_weight("equity_structure", "semis_relative"), is_proxy=True),
        ]

    def _volatility_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        vix = _series_value(ctx, "vixcls")
        return [
            _ind("vix", "VIX", vix, "higher_is_riskier", "FRED", self._indicator_weight("volatility", "vix"),
                 history=self._indicator_history(ctx, "vix")),
            _ind("realized_vol", "Realized Vol", ctx.get("trend", {}).get("realized_vol"), "higher_is_riskier", "computed", self._indicator_weight("volatility", "realized_vol")),
        ]

    def _cross_asset_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        # 9-signal confirmation hit rate (MVP simplified): cross-asset risk confirmation
        cross = ctx.get("cross_asset", {})
        return [
            _ind("cross_asset_confirmation", "Cross-asset Confirmation", cross.get("confirmation"), "higher_is_riskier", "computed", self._indicator_weight("cross_asset", "cross_asset_confirmation"), is_proxy=True),
        ]

    def _trend_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        trend = ctx.get("trend", {})
        return [
            _ind("price_vs_ma200", "Price vs MA200", trend.get("price_vs_ma200"), "lower_is_riskier", "computed", self._indicator_weight("trend", "price_vs_ma200")),
            _ind("drawdown_52w", "52W Drawdown", trend.get("drawdown_52w"), "lower_is_riskier", "computed", self._indicator_weight("trend", "drawdown_52w")),
            _ind("momentum_3m", "3M Momentum", trend.get("momentum_3m"), "lower_is_riskier", "computed", self._indicator_weight("trend", "momentum_3m")),
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
        proxy_discount = conf_mod.proxy_discount_factor()
        dimensions, dimension_bounds, available_indicator_count = self._build_dimensions(
            ctx, builders, prev_dim_scores, proxy_discount
        )
        self._renormalize_dimensions(dimensions)

        denom = sum(d.effective_weight for d in dimensions) or 1.0
        total_score = round(sum(d.effective_weight * d.score for d in dimensions) / denom, 2)

        # Risk level
        risk_level = self._level_for(total_score)

        top_drivers = self._build_drivers(
            dimensions, denom, proxy_discount, float(ctx.get("data_quality", 1.0))
        )

        # Regime
        regime_ctx = {
            "vix": _series_value(ctx, "vixcls"),
            "hy_oas": _first_value(ctx, "credit", "bamlh0a0hym2"),
            "yield_curve_10y2y": _curve_value(ctx),
            "breadth_above_ma200": ctx.get("breadth", {}).get("breadth_above_ma200"),
            "cross_asset_confirmation": ctx.get("cross_asset", {}).get("confirmation"),
            "momentum_3m": ctx.get("trend", {}).get("momentum_3m"),
        }
        regime, regime_evidence = regime_mod.infer_regime(regime_ctx)

        # Trend: compare with the most recent risk history (run.py injects prev_total_score + risk_history)
        prev_score = ctx.get("_prev_total_score")
        trend_1d = round(total_score - prev_score, 2) if prev_score is not None else None
        trend_1w, trend_1m = _history_trends(total_score, ctx.get("_risk_history"))

        # Confidence
        data_quality = float(ctx.get("data_quality", 1.0))
        availability_coverage = sum(d.coverage * d.weight for d in dimensions) / (sum(d.weight for d in dimensions) or 1.0)
        coverage = sum(d.effective_coverage * d.weight for d in dimensions) / (sum(d.weight for d in dimensions) or 1.0)
        consistency = conf_mod.consistency_from_dimension_scores([d.score for d in dimensions])
        confidence = conf_mod.compute_confidence(data_quality, coverage, consistency, self.conf_weights)

        configured_weight_total = sum(d.weight for d in dimensions) or 1.0
        score_lower_bound = round(
            max(0.0, min(100.0, sum(d.weight * dimension_bounds[d.key][0] for d in dimensions) / configured_weight_total)),
            2,
        )
        score_upper_bound = round(
            max(0.0, min(100.0, sum(d.weight * dimension_bounds[d.key][1] for d in dimensions) / configured_weight_total)),
            2,
        )
        if available_indicator_count == 0 or availability_coverage < self.insufficient_evidence_threshold:
            evidence_state: RiskEvidenceState = "insufficient_evidence"
        elif all(d.evidence_state == "complete" for d in dimensions) and availability_coverage >= 1.0:
            evidence_state = "complete"
        else:
            evidence_state = "partial"

        # #69: publish the breadth sample disclosure (qualifying/considered counts) so a
        # thinning sample is visible in the data.
        breadth_data = ctx.get("breadth")
        breadth_snapshot_value: BreadthSnapshot | None = None
        if isinstance(breadth_data, dict):
            breadth_snapshot_value = BreadthSnapshot.model_validate(breadth_data)

        return RiskModelResult(
            model_version=self.model_version,
            generated_at=now_utc(),
            total_score=total_score,
            risk_level=risk_level,
            trend_1d=trend_1d,
            trend_1w=trend_1w,
            trend_1m=trend_1m,
            dimensions=dimensions,
            cross_asset_signals=[
                CrossAssetSignal.model_validate(signal)
                for signal in ctx.get("cross_asset", {}).get("signals", [])
            ],
            top_drivers=top_drivers,
            breadth=breadth_snapshot_value,
            regime=regime,
            regime_evidence=regime_evidence,
            confidence=confidence,
            confidence_factors={
                "data_quality": round(data_quality, 4),
                "coverage": round(coverage, 4),
                "consistency": consistency,
            },
            disclaimer=DEFAULT_DISCLAIMER,
            evidence_state=evidence_state,
            evidence_coverage=round(coverage, 4),
            score_lower_bound=score_lower_bound,
            score_upper_bound=score_upper_bound,
            calibration_policy_version=self.calibration_policy_version,
            calibration_status=self.calibration_status,
        )

    def _build_dimensions(
        self,
        ctx: dict[str, Any],
        builders: dict[str, Any],
        prev_scores: dict[str, float],
        proxy_discount: float,
    ) -> tuple[list[RiskDimension], dict[str, tuple[float, float]], int]:
        dimensions: list[RiskDimension] = []
        bounds: dict[str, tuple[float, float]] = {}
        available_count = 0
        for dim_key, builder in builders.items():
            indicators = builder(ctx)
            available = [indicator for indicator in indicators if indicator.value is not None]
            missing = [indicator.key for indicator in indicators if indicator.value is None]
            available_count += len(available)
            total_indicator_weight = sum(indicator.weight for indicator in indicators) or 1.0
            available_weight = sum(indicator.weight for indicator in available)
            effective_available_weight = sum(
                indicator.weight * (proxy_discount if indicator.is_proxy else 1.0)
                for indicator in available
            )
            raw_coverage = available_weight / total_indicator_weight
            effective_coverage = effective_available_weight / total_indicator_weight
            dim_score = (
                round(sum(i.risk_score * i.weight for i in available) / sum(i.weight for i in available), 2)
                if available else 0.0
            )
            observed_weight = sum(indicator.risk_score * indicator.weight for indicator in available)
            missing_weight = sum(indicator.weight for indicator in indicators if indicator.value is None)
            bounds[dim_key] = (
                round(max(0.0, min(100.0, observed_weight / total_indicator_weight)), 2),
                round(max(0.0, min(100.0, (observed_weight + 100.0 * missing_weight) / total_indicator_weight)), 2),
            )
            evidence_state: RiskEvidenceState = (
                "insufficient_evidence" if not available else "partial" if missing else "complete"
            )
            cfg_weight = float(self.dim_cfg.get(dim_key, {}).get("weight", 0))
            dimensions.append(
                RiskDimension(
                    key=dim_key,
                    label=DIMENSION_LABELS.get(dim_key, dim_key),
                    weight=cfg_weight,
                    effective_weight=cfg_weight,
                    score=dim_score,
                    indicators=indicators,
                    coverage=round(raw_coverage, 4),
                    effective_coverage=round(effective_coverage, 4),
                    trend=_dim_trend(dim_score, prev_scores.get(dim_key)),
                    evidence_state=evidence_state,
                    missing_indicators=missing,
                )
            )
        return dimensions, bounds, available_count

    @staticmethod
    def _renormalize_dimensions(dimensions: list[RiskDimension]) -> None:
        """Redistribute missing dimension weights proportionally across available dimensions."""
        total_weight = sum(d.weight for d in dimensions if d.coverage > 0)
        total_weight = total_weight or sum(d.weight for d in dimensions) or 1.0
        for dimension in dimensions:
            dimension.effective_weight = round(dimension.weight, 4) if dimension.coverage > 0 else 0.0
        missing_weight = sum(d.weight for d in dimensions if d.coverage == 0)
        if missing_weight:
            for dimension in dimensions:
                if dimension.coverage > 0:
                    dimension.effective_weight = round(
                        dimension.weight + dimension.weight / total_weight * missing_weight, 4
                    )

    @staticmethod
    def _build_drivers(
        dimensions: list[RiskDimension],
        denominator: float,
        proxy_discount: float,
        data_quality: float,
    ) -> list[DriverContribution]:
        degrade_discount = degrade_factor() if data_quality < 1.0 else 1.0
        drivers: list[DriverContribution] = []
        for dimension in dimensions:
            available = [indicator for indicator in dimension.indicators if indicator.value is not None]
            weight_sum = sum(indicator.weight for indicator in available) or 1.0
            for indicator in available:
                drivers.append(
                    DriverContribution(
                        dimension_key=dimension.key,
                        indicator_key=indicator.key,
                        label=indicator.label,
                        contribution=round(
                            dimension.effective_weight / denominator
                            * (indicator.weight / weight_sum)
                            * indicator.risk_score,
                            4,
                        ),
                        change_1d=None,
                        evidence_ref=None,
                        is_proxy=indicator.is_proxy,
                        discount=round(
                            (proxy_discount if indicator.is_proxy else 1.0) * degrade_discount,
                            4,
                        ),
                    )
                )
        return sorted(drivers, key=lambda driver: driver.contribution, reverse=True)[:5]

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
    """Build sorted (level, predicate) rules and reject ambiguous config."""
    valid_levels = {"risk_on", "low_risk", "caution", "high_risk", "severe_risk", "crisis"}
    out: list[tuple[float, RiskLevel, Any]] = []
    for level, rule in raw.items():
        if level not in valid_levels:
            raise ValueError(f"risk_model.yaml: unknown risk level {level!r}")
        if not isinstance(rule, dict):
            raise ValueError(f"risk_model.yaml: threshold for {level} must be a mapping")
        if set(rule) - {"gte", "lt"} or not set(rule) & {"gte", "lt"}:
            raise ValueError(f"risk_model.yaml: invalid threshold rule for {level}")
        if "lt" in rule and "gte" not in rule:
            upper = float(rule["lt"])
            out.append((float("-inf"), level, lambda s, r=upper: s < r))
        elif "gte" in rule and "lt" in rule:
            lower = float(rule["gte"])
            upper = float(rule["lt"])
            if lower >= upper:
                raise ValueError(f"risk_model.yaml: invalid threshold range for {level}")
            out.append((lower, level, lambda s, lo=lower, hi=upper: lo <= s < hi))
        elif "gte" in rule:
            lower = float(rule["gte"])
            out.append((lower, level, lambda s, lo=lower: s >= lo))
    return [(level, predicate) for _, level, predicate in sorted(out, key=lambda item: item[0])]


def _series_value(ctx: dict[str, Any], key: str) -> float | None:
    macro = ctx.get("macro")
    groups = (
        (CANONICAL_MACRO_GROUPS[key],)
        if key in CANONICAL_MACRO_GROUPS
        else ("rates", "credit", "volatility", "inflation", "labor", "liquidity", "fx")
    )
    for group in groups:
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
