"""Freshness 五态判定（架构 §8.5 唯一权威实现）。

管道在 validation/freshness.py 统一判定（不信任 Provider 自报，架构 §8.4）；
analysis/freshness.py 复用本模块。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

FreshnessStatus = Literal["fresh", "delayed", "stale", "missing", "degraded"]


def evaluate_freshness(
    updated_at: str | None,
    expected_minutes: int,
    now: datetime | None = None,
) -> FreshnessStatus:
    """时间维度五态判定（相对期望更新频率；不含 degraded）。

    - fresh   : 最近更新 ≤ 1.5× 期望间隔
    - delayed : 1.5× ~ 3×
    - stale   : > 3×
    - missing : 从未有数据 / 文件缺失
    """
    if not updated_at:
        return "missing"
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return "missing"
    if now is None:
        now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)

    age_minutes = (now - updated).total_seconds() / 60.0
    if age_minutes <= 1.5 * expected_minutes:
        return "fresh"
    if age_minutes <= 3.0 * expected_minutes:
        return "delayed"
    return "stale"


def expected_interval_minutes_for(dataset: str, fallback: int) -> int:
    """从 config/sources.yaml 读取期望间隔（分钟）。"""
    from pipeline.settings import settings

    try:
        expectations = settings.load_sources().get("expectations", {})
        entry = expectations.get(dataset, {})
        minutes = int(entry.get("interval_minutes", fallback))
        return minutes if minutes > 0 else fallback
    except (FileNotFoundError, ValueError, TypeError):
        return fallback
