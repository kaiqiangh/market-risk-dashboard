"""快照累积（架构 §1.6：FedWatch 本地每日快照）。"""

from __future__ import annotations

from pipeline.fedwatch.snapshots import enrich_with_history, load_history, save_history

__all__ = ["enrich_with_history", "load_history", "save_history"]
