"""6 维风险模型（架构 §3.2/§1.8 口径红线）。

- 风险分为"模型化的市场压力估计"，非精确崩盘概率（disclaimer 固定文案）。
- 权重来自 config/risk_model.yaml；某维 coverage=0 时按剩余维度权重比例重归一化。
- 输出 RiskModelResult（pydantic 契约，score 0-100 / confidence 0-1）。
"""

from __future__ import annotations

from typing import Any

from pipeline.risk import confidence as conf_mod
from pipeline.risk import regime as regime_mod
from pipeline.risk.scoring import heuristic_risk_score
from pipeline.schemas import (
    DriverContribution,
    RiskDimension,
    RiskIndicator,
    RiskLevel,
    RiskModelResult,
)
from pipeline.settings import Settings

DIMENSION_LABELS = {
    "macro": "Macro",
    "liquidity_credit": "Liquidity & Credit",
    "equity_structure": "Equity Structure",
    "volatility": "Volatility",
    "cross_asset": "Cross Asset",
    "trend": "Trend",
}

DEFAULT_DISCLAIMER = "本页风险分数为模型化的市场压力估计，并非精确的崩盘概率，不构成投资建议。"


def _ind(key: str, label: str, value: float | None, direction: str, source: str, weight: float, is_proxy: bool = False) -> RiskIndicator:
    score = heuristic_risk_score(key, value) if value is not None else None
    return RiskIndicator(
        key=key, label=label, value=value,
        percentile=None, z_score=None,
        risk_score=score if score is not None else 50.0,  # 无映射规则时取中性分
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

    # ---- 各维指标 ----

    def _macro_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        macro = ctx.get("macro")
        rates = {m.key: m for m in getattr(macro, "rates", [])}
        credit = {m.key: m for m in getattr(macro, "credit", [])}
        dgs10 = rates.get("dgs10")
        dfii10 = rates.get("dfii10")
        dgs2 = rates.get("dgs2")
        curve = (dgs10.value - dgs2.value) if (dgs10 and dgs2 and dgs10.value is not None and dgs2.value is not None) else None
        hy = credit.get("bamlh0a0hym2")
        ig = credit.get("bamlc0a0cm")
        dxy = next((m for m in getattr(macro, "fx", []) if m.key == "dtwexbgs"), None)
        return [
            _ind("real_rate_dfii10", "10Y Real Rate", dfii10.value if dfii10 else None, "higher_is_riskier", "FRED", 5.0),
            _ind("yield_curve_10y2y", "10Y-2Y Curve", curve, "higher_is_riskier", "FRED", 5.0),
            _ind("hy_oas", "HY OAS", hy.value if hy else None, "higher_is_riskier", "FRED", 5.0),
            _ind("ig_oas", "IG OAS", ig.value if ig else None, "higher_is_riskier", "FRED", 5.0),
            _ind("dxy", "Dollar Index", dxy.value if dxy else None, "higher_is_riskier", "FRED", 5.0),
            _ind("dgs10", "10Y Yield", dgs10.value if dgs10 else None, "neutral", "FRED", 5.0),
        ]

    def _liquidity_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        macro = ctx.get("macro")
        liquidity = {m.key: m for m in getattr(macro, "liquidity", [])}
        w = liquidity.get("walcl")
        rr = liquidity.get("rrpontsyd")
        return [
            _ind("fed_balance_sheet", "Fed Balance Sheet", w.value if w else None, "neutral", "FRED", 5.0),
            _ind("reverse_repo", "Reverse Repo", rr.value if rr else None, "neutral", "FRED", 5.0),
            _ind("hy_oas", "HY OAS", _first_value(ctx, "credit", "bamlh0a0hym2"), "higher_is_riskier", "FRED", 10.0),
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
            _ind("vix", "VIX", vix, "higher_is_riskier", "FRED", 8.0),
            _ind("realized_vol", "Realized Vol", ctx.get("trend", {}).get("realized_vol"), "higher_is_riskier", "computed", 7.0),
        ]

    def _cross_asset_indicators(self, ctx: dict[str, Any]) -> list[RiskIndicator]:
        # 9 项确认信号命中率（MVP 简化）：跨资产风险确认
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

    # ---- 主流程 ----

    def score(self, ctx: dict[str, Any]) -> RiskModelResult:
        builders = {
            "macro": self._macro_indicators,
            "liquidity_credit": self._liquidity_indicators,
            "equity_structure": self._equity_structure_indicators,
            "volatility": self._volatility_indicators,
            "cross_asset": self._cross_asset_indicators,
            "trend": self._trend_indicators,
        }

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
                    trend="flat",
                )
            )

        # 重归一化：coverage=0 的维度权重按剩余维度比例重新分配
        total_weight = sum(d.weight for d in dimensions if d.coverage > 0)
        if total_weight <= 0:
            total_weight = sum(d.weight for d in dimensions) or 1.0
        for d in dimensions:
            if d.coverage > 0:
                d.effective_weight = round(d.weight, 4)
            else:
                d.effective_weight = 0.0
        # 将缺失维度权重按有效维度比例分配
        missing_weight = sum(d.weight for d in dimensions if d.coverage == 0)
        if missing_weight > 0 and total_weight > 0:
            for d in dimensions:
                if d.coverage > 0:
                    d.effective_weight = round(d.weight + d.weight / total_weight * missing_weight, 4)

        denom = sum(d.effective_weight for d in dimensions) or 1.0
        total_score = round(sum(d.effective_weight * d.score for d in dimensions) / denom, 2)

        # 风险等级
        risk_level = self._level_for(total_score)

        # Top drivers（贡献 = 有效权重 × 风险分 / 100）
        drivers: list[DriverContribution] = []
        for d in dimensions:
            for ind in d.indicators:
                if ind.value is None:
                    continue
                contribution = round(d.effective_weight * ind.risk_score / 100.0, 4)
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
            "dxy": _first_value(ctx, "fx", "dtwexbgs"),
        }
        regime, regime_evidence = regime_mod.infer_regime(regime_ctx)

        # 趋势：与最近一次 risk 历史对比（run.py 注入 prev_total_score）
        prev_score = ctx.get("_prev_total_score")
        trend_1d = round(total_score - prev_score, 2) if prev_score is not None else None

        # 置信度
        data_quality = float(ctx.get("data_quality", 1.0))
        coverage = sum(d.coverage * d.weight for d in dimensions) / (sum(d.weight for d in dimensions) or 1.0)
        consistency = conf_mod.consistency_from_dimension_scores([d.score for d in dimensions])
        confidence = conf_mod.compute_confidence(data_quality, coverage, consistency, self.conf_weights)

        return RiskModelResult(
            model_version=self.model_version,
            generated_at=_now_utc(),
            total_score=total_score,
            risk_level=risk_level,
            trend_1d=trend_1d,
            trend_1w=None,
            trend_1m=None,
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


def _parse_thresholds(raw: dict[str, Any]) -> list[tuple[RiskLevel, Any]]:
    """从 config thresholds 构建 (level, predicate)。"""
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
    # 按 (下界) 排序，保证第一个命中优先
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


def _now_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
