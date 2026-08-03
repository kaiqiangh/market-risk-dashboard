"""FedWatch probability computation (architecture §1.6 frozen: CME methodology self-computed + Fix round P0-3).

Input: Yahoo Chart API ZQ fed funds futures (current/next contract) + FRED EFFR anchor.
Computation (official CME methodology):
  implied monthly average rate = 100 − futures settlement price
  post-meeting rate EFFR(End):
    - non-month-end meeting (current-month contract method):
        EFFR(End) = (M×implied_avg − (M−N)×EFFR(Start)) / N
        where M = days in month, N = days after the meeting (inclusive), M−N = days before the meeting.
        Equivalent to the rearranged form EFFR(End)=N/(N−M)×[implied_avg−(M/N)×EFFR(Start)]
        (N=days after, M=days before, total = M+N; the N/(N−M) in the task-list formula is a typo
        in the CME doc's wording; standard derivation uses (M+N)/N).
    - month-end meeting (meeting falls in the last 7 days of the month) → next-month contract method:
        the whole next month is at the new rate → EFFR(End) ≈ 100 − next-month contract price.
  P(hike 25bp) = Δ/25bp, P(cut 25bp) = −Δ/25bp, P(hold) = 1 − both,
  where Δ = EFFR(End) − EFFR(Start) (bp), probabilities clamped to [0,1].

Constraint: free settlement history is only ~5 trading days → "change vs a week ago" shows
"insufficient data" (accumulating) instead of 0/empty until 7 days have accumulated (review P0-1).

change_1d / status are backfilled by the snapshots layer based on historical snapshots
(this module stays pure computation).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime

from pipeline.schemas import FedWatchRateProb, FedWatchSnapshot

# Month-end meeting detection window: meeting day in the last 7 days of the month → next-month contract method (CME rule)
MONTH_END_WINDOW_DAYS = 7


@dataclass
class FedWatchInput:
    """Computation input: contract prices + EFFR anchor."""

    current_contract_price: float | None  # nearest-expiring contract settlement price (e.g. ZQU26)
    next_contract_price: float | None    # next contract (for month-end meetings)
    effr: float | None                   # current FRED DFF/EFFR value
    meeting_date: str | None = None


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _meeting_parts(meeting_date: str | None) -> tuple[int, int] | None:
    """Parse the meeting date → (meeting day, days in month); None when unparseable."""
    if not meeting_date:
        return None
    try:
        parsed = datetime.fromisoformat(meeting_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.day, calendar.monthrange(parsed.year, parsed.month)[1]


def _is_month_end_meeting(meeting_date: str | None) -> bool:
    """Whether the meeting day falls in the last 7 days of the month (month-end meeting → next-month contract method)."""
    parts = _meeting_parts(meeting_date)
    if parts is None:
        return False
    day, days_in_month = parts
    return day >= days_in_month - MONTH_END_WINDOW_DAYS + 1


def _implied_end_rate(inp: FedWatchInput, implied_avg: float) -> float | None:
    """EFFR(End) (CME methodology; None when it cannot be computed)."""
    if _is_month_end_meeting(inp.meeting_date):
        if inp.next_contract_price is None:
            # Next-month contract missing → degrade to a whole-month average approximation (limited but usable)
            return implied_avg
        return 100.0 - inp.next_contract_price

    parts = _meeting_parts(inp.meeting_date)
    if parts is None:
        # No meeting date → whole-month average approximation: EFFR(End) ≈ implied monthly average
        return implied_avg

    meeting_day, days_in_month = parts
    days_before = meeting_day - 1
    days_after = days_in_month - meeting_day + 1
    if days_after <= 0:
        return implied_avg
    return (days_in_month * implied_avg - days_before * inp.effr) / days_after


def compute_fedwatch(inp: FedWatchInput) -> FedWatchSnapshot | None:
    """Compute the next meeting's hike/hold/cut probabilities using the CME method.

    Outputs probabilities for 3 target buckets (hike 25bp / hold / cut 25bp):
    P(hike) = Δ/25bp clamped to [0,1], P(hold) = 1 − P(hike) − P(cut).
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

    # Round to 6 decimal places and ensure the three buckets always sum to 1.0 (test assertion < 1e-6)
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
    """Explicit state when fewer than 7 days have accumulated (frontend shows insufficient data instead of 0/empty)."""
    return FedWatchSnapshot(
        meeting_date=None,
        effective_rate=effr if effr is not None else 0.0,
        implied_rate=0.0,
        probabilities=[],
        inferred_action="insufficient_data",
        change_1d=None,
        status="accumulating",
    )
