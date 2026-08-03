"""Snapshot accumulation (architecture §1.6: FedWatch local daily snapshots)."""

from __future__ import annotations

from pipeline.fedwatch.snapshots import enrich_with_history, load_history, save_history

__all__ = ["enrich_with_history", "load_history", "save_history"]
