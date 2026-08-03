"""历史管理（架构 §1.7：全量保留 + 切片加载；不做 90 天裁剪）。"""

from __future__ import annotations

from pipeline.storage.writer import StorageWriter

__all__ = ["StorageWriter"]
