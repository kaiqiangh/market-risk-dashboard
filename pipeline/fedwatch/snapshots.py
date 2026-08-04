"""FedWatch local daily snapshot accumulation (architecture §1.6/review P0-1).

Free settlement history is only ~5 trading days → "change vs a week ago" accumulates from launch;
before 7 days accumulate the snapshot status=accumulating, change_1d=None (frontend shows insufficient data).
"""

from __future__ import annotations

from pathlib import Path

from pipeline.schemas import FedWatchSnapshot
from pipeline.storage.writer import CorruptDataError, StorageWriter
from pipeline.utils import now_utc

#: Carry-only StorageWriter. `write_json`/`_read_json` take full paths and never read
#: `self.data_dir`, so the instance carries no state; constructing one normally would
#: mkdir the standard data directories as a side effect of every history read/write.
#: Routing through these primitives keeps atomic-write and corrupt-JSON detection in
#: their single home (pipeline/storage/writer.py) instead of reimplementing them here.
_WRITER = StorageWriter.__new__(StorageWriter)


def load_history(path: Path) -> list[dict]:
    """Read accumulated history.

    Absent and corrupt are different facts. A first run legitimately has no file, so an
    absent file reads as `[]`. A file that exists but will not parse — or is zero-length,
    the signature of an interrupted write — raises `CorruptDataError` naming the path
    (reusing `StorageWriter._read_json`). Answering corruption with `[]` is how a
    truncated history became an empty one and the next save replaced months of data with
    a single row. Valid JSON that is not a list is treated the same way: it is not a
    history, and handing it to the merge would corrupt the file.
    """
    if not path.exists():
        return []
    data = _WRITER._read_json(path, default=[])
    if not isinstance(data, list):
        raise CorruptDataError(path, "is not a list of history rows")
    return data


def save_history(path: Path, history: list[dict]) -> None:
    """Write accumulated history atomically.

    Delegates to `StorageWriter.write_json`: a temp file in the target's own directory,
    fsync, `os.replace`, and cleanup on `BaseException` (including `KeyboardInterrupt`).
    A reader observes either the previous complete file or the new complete one — never
    a half-written one.
    """
    _WRITER.write_json(path, history)


def enrich_with_history(
    snapshot: FedWatchSnapshot,
    history: list[dict],
    history_path: Path,
    today: str | None = None,
) -> FedWatchSnapshot:
    """Merge the new snapshot with history, backfilling change_1d and status.

    Rules:
    - A snapshot already exists for the same day → update that day (dedupe).
    - History < 2 days → accumulating (insufficient data).
    - History ≥ 2 days → compute the change vs yesterday for each bucket, status=ready.
    """
    today = today or now_utc()[:10]

    # Same-day dedupe (mutates the passed list in place so the caller's save_history gets the updated history)
    history[:] = [h for h in history if str(h.get("date", ""))[:10] != today]
    yesterday = max((h for h in history if str(h.get("date", ""))[:10] < today), key=lambda h: h["date"], default=None)

    history.append(
        {
            # Logical date (today) + current time: ensures per-day accumulation is testable and reproducible
            "date": f"{today}{now_utc()[10:]}",
            "meeting_date": snapshot.meeting_date,
            "effective_rate": snapshot.effective_rate,
            "implied_rate": snapshot.implied_rate,
            "inferred_action": snapshot.inferred_action,
            "probabilities": [p.model_dump() for p in snapshot.probabilities],
        }
    )
    history.sort(key=lambda h: h["date"])

    if yesterday is None or not yesterday.get("probabilities"):
        return snapshot

    prev_map = {p["target_rate"]: p["probability"] for p in yesterday["probabilities"]}
    change_1d: dict[str, float] = {}
    for prob in snapshot.probabilities:
        prev = prev_map.get(prob.target_rate)
        if prev is not None:
            change_1d[str(prob.target_rate)] = round(prob.probability - prev, 4)

    enriched = snapshot.model_copy(update={"change_1d": change_1d or None, "status": "ready"})
    return enriched
