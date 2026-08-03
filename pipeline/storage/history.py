"""History management (architecture §1.7: full retention + slice loading; no 90-day trimming)."""

from __future__ import annotations

from pipeline.storage.writer import StorageWriter

__all__ = ["StorageWriter"]
