"""FedWatch computation tests (architecture §1.6 + Fix P0-3 CME methodology)."""

from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from pipeline.fedwatch.calculator import FedWatchInput, compute_fedwatch, insufficient_data_snapshot
from pipeline.fedwatch.futures import next_contract_codes
from pipeline.fedwatch.snapshots import enrich_with_history, load_history, save_history
from pipeline.schemas import FedWatchSnapshot


def test_next_contract_codes() -> None:
    codes = next_contract_codes(dt.date(2026, 8, 3), 2)
    assert len(codes) == 2
    assert codes[0] == "ZQU26.CBT"  # Sep 2026
    assert codes[1] == "ZQZ26.CBT"  # Dec 2026


# ---------- CME methodology: P(hike)=Δ/25bp ----------

def test_compute_fedwatch_hold() -> None:
    # effr=5.25, implied rate≈5.25 → hold (whole-month average approximation, no meeting date)
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.75, next_contract_price=94.70, effr=5.25))
    assert snap is not None
    assert snap.inferred_action == "hold"
    assert snap.implied_rate == 5.25
    total = sum(p.probability for p in snap.probabilities)
    assert abs(total - 1.0) < 1e-6
    by_rate = {p.target_rate: p.probability for p in snap.probabilities}
    assert by_rate[5.25] == 1.0  # hold probability 100%


def test_compute_fedwatch_cut() -> None:
    # effr=5.25, implied rate 5.10 → Δ=-15bp → P(cut)=0.6
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.90, next_contract_price=None, effr=5.25))
    assert snap is not None
    assert snap.inferred_action == "cut"
    by_rate = {p.target_rate: p.probability for p in snap.probabilities}
    assert by_rate[5.00] == 0.6
    assert by_rate[5.25] == 0.4


def test_compute_fedwatch_hike() -> None:
    # effr=5.25, implied rate 5.45 → Δ=+20bp → P(hike)=0.8
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.55, next_contract_price=None, effr=5.25))
    assert snap is not None
    assert snap.inferred_action == "hike"
    by_rate = {p.target_rate: p.probability for p in snap.probabilities}
    assert by_rate[5.50] == 0.8
    assert by_rate[5.25] == 0.2


def test_cme_exact_25bp_hike_probability_one() -> None:
    """Δ exactly 25bp → P(hike)=1.0 (CME formula EFFR(End)=Δ/25bp)."""
    # meeting on May 1 (new rate in effect that day) → the whole month is at the new rate → EFFR(End)=implied monthly average
    snap = compute_fedwatch(
        FedWatchInput(
            current_contract_price=94.50, next_contract_price=None,
            effr=5.25, meeting_date="2026-05-01T18:00:00Z",
        )
    )
    assert snap is not None
    assert snap.inferred_action == "hike"
    by_rate = {p.target_rate: p.probability for p in snap.probabilities}
    assert by_rate[5.50] == 1.0


def test_cme_day_split_method() -> None:
    """Current-month contract method: meeting on May 12 (31 days), implied monthly average 5.30, EFFR 5.25.

    EFFR(End) = (31×5.30 − 11×5.25) / 20 = 5.3275 → Δ=7.75bp → P(hike)=0.31
    """
    snap = compute_fedwatch(
        FedWatchInput(
            current_contract_price=94.70, next_contract_price=None,
            effr=5.25, meeting_date="2026-05-12T18:00:00Z",
        )
    )
    assert snap is not None
    assert snap.implied_rate == 5.30
    by_rate = {p.target_rate: p.probability for p in snap.probabilities}
    assert abs(by_rate[5.50] - 0.31) < 0.02
    assert snap.inferred_action == "hold"


def test_cme_month_end_uses_next_contract() -> None:
    """Month-end meeting (May 31, last-7-day window) → next-month contract method.

    Next-month contract 94.60 → EFFR(End)=5.40 → Δ=+15bp → P(hike)=0.6.
    """
    snap = compute_fedwatch(
        FedWatchInput(
            current_contract_price=94.75, next_contract_price=94.60,
            effr=5.25, meeting_date="2026-05-31T18:00:00Z",
        )
    )
    assert snap is not None
    by_rate = {p.target_rate: p.probability for p in snap.probabilities}
    assert by_rate[5.50] == 0.6
    assert snap.inferred_action == "hike"


def test_insufficient_data_snapshot() -> None:
    snap = insufficient_data_snapshot(5.25)
    assert snap.status == "accumulating"
    assert snap.inferred_action == "insufficient_data"
    assert snap.probabilities == []


def test_enrich_with_history_first_day() -> None:
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.75, next_contract_price=None, effr=5.25))
    assert snap is not None
    history: list[dict] = []
    enriched = enrich_with_history(snap, history, Path("/tmp/fedwatch.json"), today="2026-08-03")
    assert enriched.status == "accumulating"  # no history → insufficient data
    assert enriched.change_1d is None
    assert len(history) == 1


def test_enrich_with_history_ready_and_change() -> None:
    snap1 = compute_fedwatch(FedWatchInput(current_contract_price=94.75, next_contract_price=None, effr=5.25))
    snap2 = compute_fedwatch(FedWatchInput(current_contract_price=94.60, next_contract_price=None, effr=5.25))
    assert snap1 is not None and snap2 is not None

    history: list[dict] = []
    enrich_with_history(snap1, history, Path("/tmp/fedwatch.json"), today="2026-08-02")
    enriched2 = enrich_with_history(snap2, history, Path("/tmp/fedwatch.json"), today="2026-08-03")
    assert enriched2.status == "ready"
    assert enriched2.change_1d is not None


def test_snapshot_roundtrip(tmp_path) -> None:
    path = tmp_path / "fedwatch-history.json"
    save_history(path, [{"date": "2026-08-02", "probs": []}])
    assert load_history(path) == [{"date": "2026-08-02", "probs": []}]
    assert load_history(tmp_path / "missing.json") == []
