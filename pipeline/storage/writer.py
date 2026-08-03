"""Storage writing (architecture §1.7/§3.5 StorageWriter).

- latest/{name}.json: envelope writing (or self-describing contract files)
- history/{series}/daily.json: full append + 30d/90d pre-slices
- metadata/*: sources / freshness / schema-version
- serialization: orjson (fast) + optional brotli precompression (build-time switch, off by default)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipeline.schemas import BaseEnvelope
from pipeline.utils import now_utc


class StorageWriter:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.latest_dir = data_dir / "latest"
        self.history_dir = data_dir / "history"
        self.metadata_dir = data_dir / "metadata"
        self.feeds_dir = data_dir / "feeds"
        for d in (self.latest_dir, self.history_dir, self.metadata_dir, self.feeds_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- Serialization ----

    @staticmethod
    def _dump(obj: Any) -> str:
        try:
            import orjson

            return orjson.dumps(obj, option=orjson.OPT_NAIVE_UTC).decode("utf-8")
        except ImportError:
            return json.dumps(obj, ensure_ascii=False, indent=2)

    def write_json(self, path: Path, obj: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._dump(obj), encoding="utf-8")
        return path

    # ---- Datasets ----

    def write_dataset(self, name: str, envelope: BaseEnvelope) -> Path:
        """latest/{name}.json (envelope structure)."""
        return self.write_json(self.latest_dir / f"{name}.json", envelope.model_dump(mode="json"))

    def write_standalone(self, name: str, obj: Any) -> Path:
        """Self-describing contract file (facts/analysis/news-translations)."""
        return self.write_json(self.latest_dir / f"{name}.json", obj)

    # ---- History + slices ----

    def write_slices(self, series_name: str, daily: list[dict[str, Any]]) -> None:
        """history/{series_name}/daily.json full + 30d/90d pre-slices (architecture §1.7)."""
        series_dir = self.history_dir / series_name
        series_dir.mkdir(parents=True, exist_ok=True)
        # Full append (dedupe by date)
        existing = self._read_json(series_dir / "daily.json", default=[])
        merged = _merge_by_date(existing, daily)
        self.write_json(series_dir / "daily.json", merged)
        # Pre-slices (the first screen loads only 30d, never the full history)
        self.write_json(series_dir / "30d.json", merged[-30:])
        self.write_json(series_dir / "90d.json", merged[-90:])
        self.write_json(series_dir / "index.json", {"series": series_name, "updated_at": now_utc(), "count": len(merged)})

    def append_history(self, series_name: str, row: dict[str, Any]) -> None:
        series_dir = self.history_dir / series_name
        series_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_json(series_dir / "daily.json", default=[])
        merged = _merge_by_date(existing, [row])
        self.write_json(series_dir / "daily.json", merged)
        self.write_json(series_dir / "30d.json", merged[-30:])
        self.write_json(series_dir / "90d.json", merged[-90:])

    def snapshot_append(self, name: str, row: dict[str, Any]) -> None:
        """feeds/{name}.json snapshot append (FedWatch accumulation, review P0-1)."""
        path = self.feeds_dir / f"{name}.json"
        history = self._read_json(path, default=[])
        today = now_utc()[:10]
        history = [h for h in history if str(h.get("date", ""))[:10] != today]
        history.append(row)
        history.sort(key=lambda h: h.get("date", ""))
        self.write_json(path, history)

    # ---- Metadata ----

    def update_freshness(self, dataset: str, status: str, reason: str) -> None:
        path = self.metadata_dir / "freshness.json"
        data = self._read_json(path, default={"schema_version": "1.0.0", "datasets": {}})
        data.setdefault("datasets", {})[dataset] = {
            "status": status,
            "reason": reason,
            "updated_at": now_utc(),
        }
        self.write_json(path, data)

    def record_translations(self, status: str, merged_items: int = 0, reason: str = "") -> None:
        """Chinese translation merge record (architecture §2 L320 metadata/translations.json, P1-6).

        status: "merged" | "skipped" | "missing"; the merge time is recorded as well.
        """
        path = self.metadata_dir / "translations.json"
        data = self._read_json(path, default={"schema_version": "1.0.0", "last_merge": None})
        data["schema_version"] = "1.0.0"
        data["updated_at"] = now_utc()
        data["last_merge"] = {
            "status": status,
            "merged_items": int(merged_items),
            "reason": reason,
            "source_file": "news.zh-translations.json",
            "merged_at": now_utc(),
        }
        self.write_json(path, data)

    def write_sources_metadata(self, status: dict[str, Any]) -> None:
        path = self.metadata_dir / "sources.json"
        self.write_json(path, {"schema_version": "1.0.0", "updated_at": now_utc(), "domains": status})

    def write_schema_version(self, version: str = "1.0.0") -> None:
        path = self.metadata_dir / "schema-version.json"
        self.write_json(path, {"schema_version": version, "updated_at": now_utc()})

    # ---- Utilities ----

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def read_latest(self, name: str) -> dict[str, Any] | None:
        return self._read_json(self.latest_dir / f"{name}.json", default=None)

    def read_history(self, series_name: str, slice_name: str = "daily") -> list[dict[str, Any]]:
        """Public read of history/{series}/{slice}.json (P2-9: replaces run.py's private _read_json access)."""
        return self._read_json(self.history_dir / series_name / f"{slice_name}.json", default=[])


def _merge_by_date(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date = {str(row.get("date", "")): row for row in existing}
    for row in incoming:
        by_date[str(row.get("date", ""))] = row
    merged = sorted(by_date.values(), key=lambda r: str(r.get("date", "")))
    return merged
