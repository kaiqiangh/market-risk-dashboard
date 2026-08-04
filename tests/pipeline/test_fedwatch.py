"""FedWatch computation tests (architecture §1.6 + Fix P0-3 CME methodology)."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

from pipeline.fedwatch.calculator import FedWatchInput, compute_fedwatch, insufficient_data_snapshot
from pipeline.fedwatch.futures import next_contract_codes
from pipeline.fedwatch.snapshots import enrich_with_history, load_history, save_history
from pipeline.schemas import FedWatchSnapshot

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DIR = REPO_ROOT / "pipeline"


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


# ---------- #63 follow-up: the accumulation file is the one that cannot be refetched ----------
#
# `load_history` used to answer a corrupt file with `[]`. That was not a failed read: the
# caller (`MacroCollector._accumulate`, macro.py:144-146) then appended today's entry to
# that empty list and saved it, so the corruption silently *reset the accumulation to day
# zero and persisted the reset*. The free settlement source carries ~5 trading days, so
# what was destroyed could not be refetched, and the only outward signal was
# `status=accumulating` — indistinguishable from a healthy newly-launched pipeline.


def _history_rows(n: int, *, start_day: int = 1) -> list[dict]:
    """`n` days of accumulated history, oldest first."""
    return [
        {
            "date": f"2026-08-{start_day + i:02d}T12:00:00Z",
            "meeting_date": "2026-09-16T18:00:00Z",
            "effective_rate": 5.25,
            "implied_rate": 5.25,
            "inferred_action": "hold",
            "probabilities": [{"target_rate": 5.25, "probability": 1.0}],
        }
        for i in range(n)
    ]


def _snapshot() -> FedWatchSnapshot:
    snap = compute_fedwatch(FedWatchInput(current_contract_price=94.75, next_contract_price=None, effr=5.25))
    assert snap is not None
    return snap


def test_corrupt_history_is_not_reset_to_one_entry(tmp_path) -> None:
    """The destructive scenario: corrupt history must not be replaced by a one-entry file.

    This is the harm itself rather than its mechanism. Even if the read were changed to
    return something other than `[]`, this test still fails if the accumulation is lost.
    """
    from pipeline.storage.writer import CorruptDataError

    path = tmp_path / "fedwatch-history.json"
    truncated = json.dumps(_history_rows(9))[:-40]
    path.write_text(truncated, encoding="utf-8")

    try:
        history = load_history(path)
    except CorruptDataError:
        # Fixed behavior: corruption is loud and the corrupt file is never overwritten.
        assert path.read_text(encoding="utf-8") == truncated
        return

    # Buggy behavior: load_history answered the corrupt file with `[]`; the merge appends
    # today's single entry and save_history persists the one-entry reset. The corrupt file
    # has been overwritten — the accumulation is gone, and this assertion is the failure.
    enrich_with_history(_snapshot(), history, path, today="2026-08-12")
    save_history(path, history)
    assert path.read_text(encoding="utf-8") == truncated, (
        "the corrupt file was overwritten — the accumulation is gone"
    )


def test_corrupt_history_raises_naming_the_path(tmp_path) -> None:
    """Corruption is named, not swallowed. The path is in the message and on the exception."""
    from pipeline.storage.writer import CorruptDataError

    path = tmp_path / "fedwatch-history.json"
    path.write_text('[{"date": "2026-08-01", "implied_ra', encoding="utf-8")

    with pytest.raises(CorruptDataError) as excinfo:
        load_history(path)

    assert "fedwatch-history.json" in str(excinfo.value)
    assert excinfo.value.path == path


def test_empty_history_file_is_corrupt_not_empty(tmp_path) -> None:
    """A zero-length file is the signature of an interrupted write, not an empty history."""
    from pipeline.storage.writer import CorruptDataError

    path = tmp_path / "fedwatch-history.json"
    path.write_text("", encoding="utf-8")

    with pytest.raises(CorruptDataError):
        load_history(path)


def test_missing_history_file_still_starts_empty(tmp_path) -> None:
    """Absent and corrupt are different facts: a first run legitimately has no file."""
    assert load_history(tmp_path / "never-written.json") == []


def test_save_history_is_atomic_on_interrupt(tmp_path, monkeypatch) -> None:
    """A kill between the temp write and the replace leaves the accumulated history intact."""
    path = tmp_path / "fedwatch-history.json"
    save_history(path, _history_rows(9))
    original = path.read_text(encoding="utf-8")

    def _die(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr("pipeline.storage.writer.os.replace", _die)
    with pytest.raises(KeyboardInterrupt):
        save_history(path, _history_rows(10))

    assert path.read_text(encoding="utf-8") == original
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 9


def test_save_history_leaves_no_temp_file_behind(tmp_path, monkeypatch) -> None:
    """An interrupted write cleans up after itself rather than littering feeds/."""
    path = tmp_path / "fedwatch-history.json"
    save_history(path, _history_rows(2))

    def _die(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr("pipeline.storage.writer.os.replace", _die)
    with pytest.raises(KeyboardInterrupt):
        save_history(path, _history_rows(3))

    assert sorted(p.name for p in path.parent.iterdir()) == ["fedwatch-history.json"]


def test_save_history_still_round_trips(tmp_path) -> None:
    """Atomicity must not change what lands on disk."""
    path = tmp_path / "fedwatch-history.json"
    rows = _history_rows(3)

    save_history(path, rows)

    assert load_history(path) == rows


def test_healthy_accumulation_still_grows(tmp_path) -> None:
    """The guard must not disturb the normal path: day N+1 appends rather than resets."""
    path = tmp_path / "fedwatch-history.json"
    save_history(path, _history_rows(9))

    history = load_history(path)
    enrich_with_history(_snapshot(), history, path, today="2026-08-12")
    save_history(path, history)

    assert len(load_history(path)) == 10


def test_corrupt_history_reaches_the_production_accumulate_path(tmp_path, monkeypatch) -> None:
    """The fix must reach `MacroCollector._accumulate`, not just the helpers it calls.

    `_accumulate` is the only production caller, and it runs on every macro collection.
    """
    from pipeline.collectors.macro import MacroCollector
    from pipeline.providers.base import ProviderRegistry
    from pipeline.settings import Settings
    from pipeline.storage.writer import CorruptDataError

    settings = Settings(_env_file=None, data_dir=tmp_path / "data", artifacts_dir=tmp_path / "artifacts")
    history_path = settings.data_dir / "feeds" / "fedwatch-history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    truncated = json.dumps(_history_rows(9))[:-40]
    history_path.write_text(truncated, encoding="utf-8")

    collector = MacroCollector(ProviderRegistry(settings), settings)

    with pytest.raises(CorruptDataError):
        collector._accumulate(_snapshot())

    assert history_path.read_text(encoding="utf-8") == truncated


# ---- #63 guard: atomic-write and corrupt-JSON detection each have exactly one home ----

_ATOMIC_WRITE_LITERAL = re.compile(r"tempfile\.mkstemp")
#: The corrupt-JSON primitive is the JSONDecodeError→CorruptDataError translation in
#: `_read_json` (`raise CorruptDataError(...) from exc`). Constructing CorruptDataError
#: elsewhere — e.g. snapshots.py's "not a list of history rows" shape check — reuses the
#: exception type from its single home and is not a second parsing primitive.
_CORRUPT_JSON_LITERAL = re.compile(r"raise CorruptDataError.*from exc")


def _pipeline_files_with(pattern: re.Pattern[str]) -> list[str]:
    """Every `pipeline/**/*.py` file containing a line matching `pattern` (relative paths)."""
    files: set[str] = set()
    for path in sorted(PIPELINE_DIR.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            if pattern.search(line):
                files.add(relative)
                break
    return sorted(files)


def test_atomic_write_and_corrupt_json_detection_each_have_one_home() -> None:
    """AC (#63 ruling): atomic write and corrupt-JSON detection have exactly one home.

    `snapshots.py` routes through `pipeline/storage/writer.py` (`StorageWriter.write_json`
    and `_read_json`). A second `tempfile.mkstemp`/`os.replace` block or a second
    JSONDecodeError→CorruptDataError mapping would split the primitive across two homes —
    the same one-home violation #62 existed to kill.
    """
    atomic = _pipeline_files_with(_ATOMIC_WRITE_LITERAL)
    assert atomic == ["pipeline/storage/writer.py"], (
        "atomic write must have exactly one home, pipeline/storage/writer.py; found:\n"
        + "\n".join(atomic)
    )

    corrupt = _pipeline_files_with(_CORRUPT_JSON_LITERAL)
    assert corrupt == ["pipeline/storage/writer.py"], (
        "corrupt-JSON detection must have exactly one home, pipeline/storage/writer.py; found:\n"
        + "\n".join(corrupt)
    )
