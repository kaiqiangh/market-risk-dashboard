"""Storage writing (architecture §1.7/§3.5 StorageWriter).

- latest/{name}.json: envelope writing (or self-describing contract files)
- history/{series}/daily.json: full append + 30d/90d pre-slices
- metadata/*: sources / freshness / schema-version
- serialization: orjson (fast) + optional brotli precompression (build-time switch, off by default)
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipeline.schemas import BaseEnvelope
from pipeline.schemas.envelope import SCHEMA_VERSION
from pipeline.schemas.metadata import METADATA_SCHEMA_VERSION
from pipeline.utils import now_utc


class StorageError(Exception):
    """Base class for storage faults that must reach a human instead of a default value."""


class CorruptDataError(StorageError):
    """An existing file is present but could not be parsed.

    Raised in place of returning the caller's default. Returning the default is what
    turned a truncated history file into an empty one: the merge saw no rows, and the
    next write replaced months of data with a single row.
    """

    def __init__(self, path: Path, reason: str) -> None:
        self.path: Path = Path(path)
        self.reason: str = reason
        super().__init__(f"{self.path} {reason}")


class UndatedRowError(StorageError):
    """A history row carries no usable `date`.

    History rows are keyed by date when merging. A row with no date keyed to `""`, so
    every undated row silently overwrote the previous one and the loss left no trace.
    """

    def __init__(self, row: dict[str, Any], *, series: str, reason: str) -> None:
        self.row: dict[str, Any] = row
        self.series: str = series
        self.reason: str = reason
        super().__init__(f"history row in {series!r} {reason}: {row!r}")


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
        """Write `obj` to `path` atomically.

        The payload is written to a temp file **in the target's own directory** and then
        moved onto the target with `os.replace`, which is atomic within a filesystem. A
        reader therefore observes either the previous complete file or the new complete
        one — never a half-written one.

        The same-directory requirement is not cosmetic. A temp file on another filesystem
        (`/tmp`, typically) degrades `os.replace` into a copy, which is interruptible, and
        the guarantee quietly disappears.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._dump(obj)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            # BaseException, not Exception: KeyboardInterrupt and SystemExit are precisely
            # the interruptions this method exists to survive, and neither is an Exception.
            tmp_path.unlink(missing_ok=True)
            raise
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
        # Validate before the first write: a rejected batch must leave the series untouched.
        merged = _merge_by_date(existing, daily, series=series_name)
        self.write_json(series_dir / "daily.json", merged)
        # Pre-slices (the first screen loads only 30d, never the full history)
        self.write_json(series_dir / "30d.json", merged[-30:])
        self.write_json(series_dir / "90d.json", merged[-90:])
        self.write_json(series_dir / "index.json", {"series": series_name, "updated_at": now_utc(), "count": len(merged)})

    def append_history(self, series_name: str, row: dict[str, Any]) -> None:
        series_dir = self.history_dir / series_name
        series_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_json(series_dir / "daily.json", default=[])
        merged = _merge_by_date(existing, [row], series=series_name)
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

    def read_freshness_raw(self) -> dict[str, Any]:
        """The freshness metadata file as it stands, or an empty shell if absent.

        Used by :class:`~pipeline.storage.outcomes.RunOutcomes` to carry forward datasets a
        partial run did not attempt.
        """
        path = self.metadata_dir / "freshness.json"
        # The absent-file shell must match what a real run writes (outcomes renders both
        # metadata files with METADATA_SCHEMA_VERSION) — a restated literal drifted to 1.1.0.
        return self._read_json(path, default={"schema_version": METADATA_SCHEMA_VERSION, "datasets": {}})

    def read_sources_raw(self) -> dict[str, Any]:
        """The sources metadata file as it stands, or an empty shell if absent.

        Used by :class:`~pipeline.storage.outcomes.RunOutcomes` to carry forward domains a
        partial run did not attempt.
        """
        path = self.metadata_dir / "sources.json"
        return self._read_json(path, default={"schema_version": METADATA_SCHEMA_VERSION, "domains": {}})

    def write_freshness_metadata(self, payload: dict[str, Any]) -> None:
        """Write the whole freshness file in one shot.

        Replaces the previous per-dataset read-modify-write. Writing it once from a complete
        record is what guarantees every registered dataset appears on every run — the
        incremental version silently omitted anything a collector never got to, making
        "never ran" indistinguishable from "ran fine".
        """
        self.write_json(self.metadata_dir / "freshness.json", payload)

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

    def write_sources_metadata(self, payload: dict[str, Any]) -> None:
        """Write the whole provider-health file in one shot.

        Takes the complete document rather than just the domain map: the document is now a
        projection of the run outcome record (see
        :meth:`~pipeline.storage.outcomes.RunOutcomes.sources_projection`), and wrapping a
        bare domain map here would let this method decide a ``schema_version`` the projection
        already decided.
        """
        self.write_json(self.metadata_dir / "sources.json", payload)

    def write_schema_version(self, version: str = SCHEMA_VERSION) -> None:
        """Publish the data-contract version marker (defaults to the live SCHEMA_VERSION)."""
        path = self.metadata_dir / "schema-version.json"
        self.write_json(path, {"schema_version": version, "updated_at": now_utc()})

    # ---- Utilities ----

    def _read_json(self, path: Path, default: Any) -> Any:
        """Read JSON from `path`; `default` is returned only when the file is absent.

        Absent and corrupt are different facts about the world. A first run legitimately
        has no file. A file that exists but will not parse is a fault, and answering it
        with `default` is how a truncated history became an empty one.

        `OSError` is deliberately not caught either: an unreadable file is not an empty
        one, and the exception already names the path loudly. Wrapping it in
        `CorruptDataError` would mislabel a permissions problem as data corruption.
        """
        if not path.exists():
            return default
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise CorruptDataError(path, "is empty (the signature of an interrupted write)")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptDataError(path, f"is not valid JSON: {exc}") from exc

    def read_latest(self, name: str) -> dict[str, Any] | None:
        return self._read_json(self.latest_dir / f"{name}.json", default=None)

    def read_freshness(self) -> dict[str, Any]:
        """Public read of metadata/freshness.json's `datasets` map (empty before the first run)."""
        data = self._read_json(self.metadata_dir / "freshness.json", default={})
        datasets = data.get("datasets", {}) if isinstance(data, dict) else {}
        return datasets if isinstance(datasets, dict) else {}

    def read_history(self, series_name: str, slice_name: str = "daily") -> list[dict[str, Any]]:
        """Public read of history/{series}/{slice}.json (P2-9: replaces run.py's private _read_json access)."""
        return self._read_json(self.history_dir / series_name / f"{slice_name}.json", default=[])


def _row_date(row: dict[str, Any], *, series: str) -> str:
    """Return the merge key for `row`, refusing rows that have none.

    Every row that reaches here becomes a dictionary key. Rows without a date used to
    share the key `""`, which made them overwrite one another; the merge then reported
    success and the caller never learned that rows had vanished.
    """
    raw = row.get("date")
    if raw is None:
        raise UndatedRowError(row, series=series, reason="has no `date`")
    key = str(raw).strip()
    if not key:
        raise UndatedRowError(row, series=series, reason="has a blank `date`")
    return key


def _merge_by_date(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    series: str = "<unknown>",
) -> list[dict[str, Any]]:
    """Merge `incoming` onto `existing`, deduplicating by date.

    Raises `UndatedRowError` — before anything is written — if either side contains a
    row with no usable date. Rows already on disk are checked as well as new ones: an
    undated row that predates this fix is still a row that will be lost silently.
    """
    by_date = {_row_date(row, series=series): row for row in existing}
    for row in incoming:
        by_date[_row_date(row, series=series)] = row
    merged = sorted(by_date.values(), key=lambda r: str(r.get("date", "")))
    return merged
