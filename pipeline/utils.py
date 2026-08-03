"""管道共享工具（架构 §8.2 时间约定）。

所有原始时间一律 ISO 8601 UTC + Z 后缀（`2026-08-03T10:00:00Z`）。
`now_utc()` 为全管道唯一权威实现（P2-8：消除 13 处 `_now_utc` 重复定义）。
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> str:
    """当前 UTC 时间，ISO 8601 + Z（架构 §8.2）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
