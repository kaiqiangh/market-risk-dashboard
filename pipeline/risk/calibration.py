"""离线校准引擎（架构 §1.8 冻结：2008/2018/2020 三段）。

数据全部免费可得：FRED VIXCLS/BAMLH0A0HYM2/DGS10 + yfinance SPX 历史。
评估指标（PRD §15 子集）：提前预警时间、风险分数变化速度、最大回撤、
未来 5/10/20/30 日波动率、风险等级稳定性。
口径红线：校准完成前 UI 不得称风险分数为"精确崩盘概率"。
"""

from __future__ import annotations

from typing import Any

from pipeline.risk.scoring import heuristic_risk_score

CALIBRATION_WINDOWS = {
    "2008": {"start": "2008-08-01", "end": "2009-03-31", "note": "2008 金融危机"},
    "2018": {"start": "2018-09-01", "end": "2018-12-31", "note": "2018 Q4 抛售"},
    "2020": {"start": "2020-02-01", "end": "2020-04-30", "note": "COVID 崩盘"},
}


def composite_score(vix: float | None, hy: float | None, drawdown: float | None) -> float:
    """简化综合风险分（0-100）：VIX + HY OAS + 回撤的加权组合。"""
    scores = [
        heuristic_risk_score("vix", vix),
        heuristic_risk_score("hy_oas", hy),
        heuristic_risk_score("drawdown_52w", drawdown),
    ]
    present = [s for s in scores if s is not None]
    if not present:
        return 50.0
    return round(sum(present) / len(present), 2)


def evaluate_segment(
    dates: list[str],
    vix_series: list[float | None],
    hy_series: list[float | None],
    spx_series: list[float],
    segment: str,
) -> dict[str, Any]:
    """对单段窗口计算评估指标。"""
    scores: list[float] = []
    for i in range(len(dates)):
        drawdown = _drawdown(spx_series[: i + 1])
        scores.append(composite_score(vix_series[i] if i < len(vix_series) else None,
                                      hy_series[i] if i < len(hy_series) else None,
                                      drawdown))

    peak_idx = spx_series.index(max(spx_series)) if spx_series else 0
    max_dd = _max_drawdown(spx_series) if spx_series else None

    # 提前预警：风险分首次 ≥ 60 距峰值的天数（负数 = 峰值前预警）
    early_warning_days: int | None = None
    for i, s in enumerate(scores):
        if s >= 60:
            early_warning_days = i - peak_idx
            break

    # 变化速度：风险分从 40 → 60 的最短天数
    speed_days: int | None = None
    start_idx: int | None = None
    for i, s in enumerate(scores):
        if s >= 40 and start_idx is None:
            start_idx = i
        if start_idx is not None and s >= 60:
            speed_days = i - start_idx
            break

    # 未来 5/10/20/30 日波动率（从峰值后）
    future_vol: dict[str, float | None] = {}
    for horizon in (5, 10, 20, 30):
        future_vol[f"vol_{horizon}d"] = _future_vol(spx_series, peak_idx, horizon)

    # 风险等级稳定性：分数跨 40/60 阈值的切换次数
    switches = 0
    prev_level = _level(scores[0]) if scores else None
    for s in scores:
        level = _level(s)
        if level != prev_level:
            switches += 1
            prev_level = level

    return {
        "segment": segment,
        "note": CALIBRATION_WINDOWS[segment]["note"],
        "n_days": len(dates),
        "max_drawdown_pct": round(max_dd * 100.0, 2) if max_dd is not None else None,
        "early_warning_days_vs_peak": early_warning_days,
        "speed_40_to_60_days": speed_days,
        "future_vol": future_vol,
        "level_switches": switches,
        "score_first": scores[0] if scores else None,
        "score_max": max(scores) if scores else None,
        "score_last": scores[-1] if scores else None,
    }


def _drawdown(series: list[float]) -> float | None:
    if not series:
        return None
    peak = max(series)
    if peak == 0:
        return None
    return (series[-1] - peak) / peak


def _max_drawdown(series: list[float]) -> float | None:
    """窗口内最大回撤（峰值→谷值的最坏值，架构 §15 评估指标）。"""
    if not series:
        return None
    peak = series[0]
    worst = 0.0
    for value in series:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return worst


def _future_vol(series: list[float], start: int, horizon: int) -> float | None:
    import math

    window = series[start : start + horizon]
    if len(window) < 3:
        return None
    returns = [(window[i] - window[i - 1]) / window[i - 1] for i in range(1, len(window)) if window[i - 1] != 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(var) * 100.0, 2)


def _level(score: float) -> str:
    if score >= 80:
        return "severe"
    if score >= 60:
        return "high"
    if score >= 40:
        return "caution"
    return "low"
