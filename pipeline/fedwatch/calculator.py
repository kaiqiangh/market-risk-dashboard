"""FedWatch 概率自算（架构 §1.6 冻结：CME 方法论自算 + Fix 轮次 P0-3）。

输入：Yahoo Chart API ZQ 联邦基金期货（当前/下一合约）+ FRED EFFR 锚点。
计算（CME 官方方法论）：
  隐含月均利率 = 100 − 期货结算价
  会议后利率 EFFR(End)：
    - 非月底会议（当月合约法）：
        EFFR(End) = (M×隐含月均 − (M−N)×EFFR(Start)) / N
        其中 M=当月天数、N=会议后天数（含会议日）、M−N=会议前天数。
        等价于 EFFR(End)=N/(N−M)×[隐含月均−(M/N)×EFFR(Start)] 的整理形式
        （N=会议后天数、M=会议前天数、总天数= M+N；任务清单公式中的 N/(N−M)
        系 CME 文档口径的笔误，按标准推导取 (M+N)/N）。
    - 月底会议（会议落在当月最后 7 天）→ 下一月合约法：
        整个下月处于新利率 → EFFR(End) ≈ 100 − 下一月合约价。
  P(加息 25bp) = Δ/25bp，P(降息 25bp) = −Δ/25bp，P(维持) = 1 − 两者，
  其中 Δ = EFFR(End) − EFFR(Start)（bp），概率钳制在 [0,1]。

约束：免费结算历史仅约 5 个交易日 → "较一周前变化"在积累满 7 天前显示
"数据积累中（insufficient data）"而非 0/空值（评审 P0-1）。

change_1d / status 由 snapshots 层基于历史快照回填（本模块保持纯计算）。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime

from pipeline.schemas import FedWatchRateProb, FedWatchSnapshot

# 月底会议判定窗口：会议日落在当月最后 7 天 → 用下一月合约法（CME 规则）
MONTH_END_WINDOW_DAYS = 7


@dataclass
class FedWatchInput:
    """计算输入：合约价格 + EFFR 锚点。"""

    current_contract_price: float | None  # 最近到期合约结算价（如 ZQU26）
    next_contract_price: float | None    # 下一合约（月底会议用）
    effr: float | None                   # FRED DFF/EFFR 当前值
    meeting_date: str | None = None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _meeting_parts(meeting_date: str | None) -> tuple[int, int] | None:
    """解析会议日期 → (会议日, 当月天数)；无法解析返回 None。"""
    if not meeting_date:
        return None
    try:
        parsed = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.day, calendar.monthrange(parsed.year, parsed.month)[1]


def _is_month_end_meeting(meeting_date: str | None) -> bool:
    """会议日是否落在当月最后 7 天（月底会议 → 下一月合约法）。"""
    parts = _meeting_parts(meeting_date)
    if parts is None:
        return False
    day, days_in_month = parts
    return day >= days_in_month - MONTH_END_WINDOW_DAYS + 1


def _implied_end_rate(inp: FedWatchInput, implied_avg: float) -> float | None:
    """EFFR(End)（CME 方法论；无法计算返回 None）。"""
    if _is_month_end_meeting(inp.meeting_date):
        if inp.next_contract_price is None:
            # 下一月合约缺失 → 退化为整月平均近似（信息有限但可用）
            return implied_avg
        return 100.0 - inp.next_contract_price

    parts = _meeting_parts(inp.meeting_date)
    if parts is None:
        # 无会议日期 → 整月平均近似：EFFR(End) ≈ 隐含月均
        return implied_avg

    meeting_day, days_in_month = parts
    days_before = meeting_day - 1
    days_after = days_in_month - meeting_day + 1
    if days_after <= 0:
        return implied_avg
    return (days_in_month * implied_avg - days_before * inp.effr) / days_after


def compute_fedwatch(inp: FedWatchInput) -> FedWatchSnapshot | None:
    """按 CME 方法计算下一次会议加息/降息/维持概率。

    输出 3 个目标区间（加息 25bp / 维持 / 降息 25bp）的概率，
    P(加息) = Δ/25bp 钳制 [0,1]，P(维持) = 1 − P(加息) − P(降息)。
    """
    if inp.effr is None:
        return None

    contract_price = inp.current_contract_price if inp.current_contract_price is not None else inp.next_contract_price
    if contract_price is None:
        return None

    implied_avg = 100.0 - contract_price
    effr_end = _implied_end_rate(inp, implied_avg)
    if effr_end is None:
        return None

    delta_bp = (effr_end - inp.effr) * 100.0
    p_hike = _clamp(delta_bp / 25.0)
    p_cut = _clamp(-delta_bp / 25.0)
    p_hold = _clamp(1.0 - p_hike - p_cut)

    # 四舍五入到 6 位小数并保证三档之和恒为 1.0（测试断言 < 1e-6）
    p_hike_r = round(p_hike, 6)
    p_cut_r = round(p_cut, 6)
    p_hold_r = round(_clamp(1.0 - p_hike_r - p_cut_r), 6)

    probabilities = [
        FedWatchRateProb(target_rate=round(inp.effr + 0.25, 4), probability=p_hike_r, change_1d=None),
        FedWatchRateProb(target_rate=round(inp.effr, 4), probability=p_hold_r, change_1d=None),
        FedWatchRateProb(target_rate=round(inp.effr - 0.25, 4), probability=p_cut_r, change_1d=None),
    ]

    if p_hike_r > 0.5:
        action = "hike"
    elif p_cut_r > 0.5:
        action = "cut"
    else:
        action = "hold"

    return FedWatchSnapshot(
        meeting_date=inp.meeting_date,
        effective_rate=round(inp.effr, 4),
        implied_rate=round(implied_avg, 4),
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
