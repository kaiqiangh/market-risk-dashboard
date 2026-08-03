"""存储写入（架构 §1.7/§3.5 StorageWriter）。

- latest/{name}.json：envelope 写入（或自描述契约文件）
- history/{series}/daily.json：全量追加 + 30d/90d 预切片
- metadata/*：sources / freshness / schema-version
- 序列化：orjson（fast）+ 可选 brotli 预压缩（构建期开关，默认关）
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipeline.schemas import BaseEnvelope


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StorageWriter:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.latest_dir = data_dir / "latest"
        self.history_dir = data_dir / "history"
        self.metadata_dir = data_dir / "metadata"
        self.feeds_dir = data_dir / "feeds"
        for d in (self.latest_dir, self.history_dir, self.metadata_dir, self.feeds_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 序列化 ----

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

    # ---- 数据集 ----

    def write_dataset(self, name: str, envelope: BaseEnvelope) -> Path:
        """latest/{name}.json（envelope 结构）。"""
        return self.write_json(self.latest_dir / f"{name}.json", envelope.model_dump(mode="json"))

    def write_standalone(self, name: str, obj: Any) -> Path:
        """自描述契约文件（facts/analysis/news-translations）。"""
        return self.write_json(self.latest_dir / f"{name}.json", obj)

    # ---- 历史 + 切片 ----

    def write_slices(self, series_name: str, daily: list[dict[str, Any]]) -> None:
        """history/{series_name}/daily.json 全量 + 30d/90d 预切片（架构 §1.7）。"""
        series_dir = self.history_dir / series_name
        series_dir.mkdir(parents=True, exist_ok=True)
        # 全量追加（按日期去重）
        existing = self._read_json(series_dir / "daily.json", default=[])
        merged = _merge_by_date(existing, daily)
        self.write_json(series_dir / "daily.json", merged)
        # 预切片（首屏只加载 30d，绝不加载全量）
        self.write_json(series_dir / "30d.json", merged[-30:])
        self.write_json(series_dir / "90d.json", merged[-90:])
        self.write_json(series_dir / "index.json", {"series": series_name, "updated_at": _now_utc(), "count": len(merged)})

    def append_history(self, series_name: str, row: dict[str, Any]) -> None:
        series_dir = self.history_dir / series_name
        series_dir.mkdir(parents=True, exist_ok=True)
        existing = self._read_json(series_dir / "daily.json", default=[])
        merged = _merge_by_date(existing, [row])
        self.write_json(series_dir / "daily.json", merged)
        self.write_json(series_dir / "30d.json", merged[-30:])
        self.write_json(series_dir / "90d.json", merged[-90:])

    def snapshot_append(self, name: str, row: dict[str, Any]) -> None:
        """feeds/{name}.json 快照追加（FedWatch 累积，评审 P0-1）。"""
        path = self.feeds_dir / f"{name}.json"
        history = self._read_json(path, default=[])
        today = _now_utc()[:10]
        history = [h for h in history if str(h.get("date", ""))[:10] != today]
        history.append(row)
        history.sort(key=lambda h: h.get("date", ""))
        self.write_json(path, history)

    # ---- 元数据 ----

    def update_freshness(self, dataset: str, status: str, reason: str) -> None:
        path = self.metadata_dir / "freshness.json"
        data = self._read_json(path, default={"schema_version": "1.0.0", "datasets": {}})
        data.setdefault("datasets", {})[dataset] = {
            "status": status,
            "reason": reason,
            "updated_at": _now_utc(),
        }
        self.write_json(path, data)

    def write_sources_metadata(self, status: dict[str, Any]) -> None:
        path = self.metadata_dir / "sources.json"
        self.write_json(path, {"schema_version": "1.0.0", "updated_at": _now_utc(), "domains": status})

    def write_schema_version(self, version: str = "1.0.0") -> None:
        path = self.metadata_dir / "schema-version.json"
        self.write_json(path, {"schema_version": version, "updated_at": _now_utc()})

    # ---- 工具 ----

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def read_latest(self, name: str) -> dict[str, Any] | None:
        return self._read_json(self.latest_dir / f"{name}.json", default=None)


def _merge_by_date(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date = {str(row.get("date", "")): row for row in existing}
    for row in incoming:
        by_date[str(row.get("date", ""))] = row
    merged = sorted(by_date.values(), key=lambda r: str(r.get("date", "")))
    return merged
