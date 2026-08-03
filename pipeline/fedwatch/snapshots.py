"""FedWatch local daily snapshot accumulation (architecture §1.6/review P0-1).

Free settlement history is only ~5 trading days → "change vs a week ago" accumulates from launch;
before 7 days accumulate the snapshot status=accumulating, change_1d=None (frontend shows insufficient data).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.schemas import FedWatchSnapshot
from pipeline.utils import now_utc


def load_history(path: Path) -> list[dict]:
    """Read accumulated history (empty list when the file does not exist)."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_history(path: Path, history: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


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
