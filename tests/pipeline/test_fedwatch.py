"""FedWatch 计算测试（架构 §1.6）。"""

from __future__ import annotations

import json

from pipeline.fedwatch.calculator import FedWatchInput, compute_fedwatch, insufficient_data_snapshot
from pipeline.fedwatch.futures import next_contract_codes
from pipeline.fedwatch.snapshots import enrich_with_history, load_history, save_history
from pipeline.schemas import FedWatchSnapshot


def test_next_contract_codes() -> None:
    import datetime

    codes = next_contract_codes(datetime.date(2026, 8, 3), 2)
    assert len(codes) == 2
    assert codes[0] == "ZQU26.CBT"  # Sep 2026
    assert codes[1] == "ZQZ26.CBT"  # Dec 2026


def test_compute_fedwatch_hold() -> None:
    # effr=5.25，隐含利率≈5.25 → 维持
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.75, next_contract_price=94.70, effr=5.25))
    assert snap is not None
    assert snap.inferred_action == "hold"
    assert snap.implied_rate == 5.25
    total = sum(p.probability for p in snap.probabilities)
    assert abs(total - 1.0) < 1e-6


def test_compute_fedwatch_cut() -> None:
    # effr=5.25，隐含利率 5.10 → 降息倾向（隐含利率明显低于锚点）
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.90, next_contract_price=None, effr=5.25))
    assert snap is not None
    assert snap.inferred_action == "cut"


def test_compute_fedwatch_hike() -> None:
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.55, next_contract_price=None, effr=5.25))
    assert snap is not None
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
    enriched = enrich_with_history(snap, history, __import__("pathlib").Path("/tmp/fedwatch.json"), today="2026-08-03")
    assert enriched.status == "accumulating"  # 无历史 → 数据积累中
    assert enriched.change_1d is None
    assert len(history) == 1


def test_enrich_with_history_ready_and_change() -> None:
    snap1 = compute_fedwatch(FedWatchInput(current_contract_price=94.75, next_contract_price=None, effr=5.25))
    snap2 = compute_fedwatch(FedWatchInput(current_contract_price=94.60, next_contract_price=None, effr=5.25))
    assert snap1 is not None and snap2 is not None

    history: list[dict] = []
    enrich_with_history(snap1, history, __import__("pathlib").Path("/tmp/fedwatch.json"), today="2026-08-02")
    enriched2 = enrich_with_history(snap2, history, __import__("pathlib").Path("/tmp/fedwatch.json"), today="2026-08-03")
    assert enriched2.status == "ready"
    assert enriched2.change_1d is not None


def test_snapshot_roundtrip(tmp_path) -> None:
    path = tmp_path / "fedwatch-history.json"
    save_history(path, [{"date": "2026-08-02", "probs": []}])
    assert load_history(path) == [{"date": "2026-08-02", "probs": []}]
    assert load_history(tmp_path / "missing.json") == []
