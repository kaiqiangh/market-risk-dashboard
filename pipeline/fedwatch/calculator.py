"""FedWatch 概率自算（架构 §1.6 冻结：CME 方法论自算）。

输入：Yahoo Chart API ZQ 联邦基金期货（当前/下一合约）+ FRED EFFR 锚点。
计算：隐含利率 = 100 − 期货结算价；按 CME 方法映射到目标区间（25bp 步长）。
约束：免费结算历史仅约 5 个交易日 → "较一周前变化"在积累满 7 天前显示
"数据积累中（insufficient data）"而非 0/空值（评审 P0-1）。

change_1d / status 由 snapshots 层基于历史快照回填（本模块保持纯计算）。
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.schemas import FedWatchRateProb, FedWatchSnapshot


@dataclass
class FedWatchInput:
    """计算输入：合约价格 + EFFR 锚点。"""

    current_contract_price: float | None  # 最近到期合约结算价（如 ZQU26）
    next_contract_price: float | None    # 下一合约（月底会议用）
    effr: float | None                   # FRED DFF/EFFR 当前值
    meeting_date: str | None = None


def compute_fedwatch(inp: FedWatchInput) -> FedWatchSnapshot | None:
    """按 CME 方法计算下一次会议加息/降息/维持概率。

    简化方法（MVP）：以 EFFR 为锚点，隐含利率 = 100 − 合约价；
    对目标利率区间（锚点 ± 25bp 步长）分配概率：按隐含利率与区间的距离
    做归一化权重（距离越近概率越高）。月底会议用下一月合约。
    """
    if inp.effr is None:
        return None

    contract_price = inp.current_contract_price if inp.current_contract_price is not None else inp.next_contract_price
    if contract_price is None:
        return None

    implied_rate = 100.0 - contract_price

    # 候选区间：围绕 EFFR 的 ±3 档（25bp 步长）
    candidates = [round(inp.effr + i * 0.25, 4) for i in (-3, -2, -1, 0, 1, 2, 3)]
    weights = [max(0.0, 1.0 - abs(implied_rate - rate) / 0.25) for rate in candidates]
    total = sum(weights) or 1.0
    probabilities = [
        FedWatchRateProb(target_rate=rate, probability=round(w / total, 4), change_1d=None)
        for rate, w in zip(candidates, weights)
    ]

    top = max(probabilities, key=lambda p: p.probability)
    if top.target_rate > inp.effr + 0.125:
        action = "hike"
    elif top.target_rate < inp.effr - 0.125:
        action = "cut"
    else:
        action = "hold"

    return FedWatchSnapshot(
        meeting_date=inp.meeting_date,
        effective_rate=round(inp.effr, 4),
        implied_rate=round(implied_rate, 4),
        probabilities=probabilities,
        inferred_action=action,
        change_1d=None,
        status="accumulating",
    )


def insufficient_data_snapshot(effr: float | None) -> FedWatchSnapshot:
    """积累未满 7 天时的明确状态（前端显示 insufficient data 而非 0/空值）。"""
    return FedWatchSnapshot(
        meeting_date=None,
        effective_rate=effr if effr is not None else 0.0,
        implied_rate=0.0,
        probabilities=[],
        inferred_action="insufficient_data",
        change_1d=None,
        status="accumulating",
    )
