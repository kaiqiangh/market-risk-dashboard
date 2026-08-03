"""Market Regime 规则引擎（架构 P0-5：规则引擎先落地，模型化放 V2）。

9 状态：goldilocks / risk_on / disinflation / reflation / late_cycle /
stagflation / liquidity_stress / risk_off / crisis。
规则基于阈值组合（VIX/利差/曲线/宽度/跨资产/动量），输出判定依据（可解释性）。
"""

from __future__ import annotations

from typing import Any


def infer_regime(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """输入上下文（vix/hy_oas/yield_curve/breadth/cross_asset/momentum/dxy），
    返回 (regime, evidence_list)。"""
    vix = ctx.get("vix")
    hy_oas = ctx.get("hy_oas")
    curve = ctx.get("yield_curve_10y2y")
    breadth = ctx.get("breadth_above_ma200")
    cross = ctx.get("cross_asset_confirmation")
    momentum = ctx.get("momentum_3m")
    dxy = ctx.get("dxy")

    evidence: list[str] = []

    # 危机/风险规避优先
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

    # 流动性压力
    if hy_oas is not None and hy_oas >= 5.0:
        evidence.append(f"HY OAS={hy_oas:.2f} ≥ 5.0")
        return "liquidity_stress", evidence

    # 滞胀：曲线倒挂 + 高利率压力 + 弱动量
    if curve is not None and curve < 0 and (momentum is not None and momentum < 0):
        evidence.append(f"Yield curve={curve:.2f} < 0 且动量={momentum:.1f} < 0")
        return "stagflation", evidence

    # 再通胀：曲线趋陡 + 强动量 + 美元走弱
    if curve is not None and curve > 0.5 and (momentum is None or momentum > 5):
        evidence.append(f"Yield curve={curve:.2f} > 0.5 且动量较强")
        return "reflation", evidence

    # 通缩：曲线倒挂 + 弱动量 + 波动率中性
    if curve is not None and curve < 0:
        evidence.append(f"Yield curve={curve:.2f} < 0")
        return "disinflation", evidence

    # 晚周期：宽信用但波动率上行 + 跨资产确认偏风险
    if cross is not None and cross >= 0.55 and (vix is not None and vix >= 18):
        evidence.append(f"Cross-asset={cross:.2f} ≥ 0.55 且 VIX={vix:.1f} ≥ 18")
        return "late_cycle", evidence

    # 金发姑娘：低波动 + 正动量 + 宽度健康
    if (vix is None or vix < 18) and (momentum is None or momentum > 0) and (breadth is None or breadth > 0.5):
        evidence.append("低波动 + 正动量 + 宽度健康")
        return "goldilocks", evidence

    # 风险偏好（risk_on）
    if (vix is not None and vix < 20) or (momentum is not None and momentum > 5):
        evidence.append("波动率低或动量强")
        return "risk_on", evidence

    evidence.append("默认：late_cycle（无强信号）")
    return "late_cycle", evidence
