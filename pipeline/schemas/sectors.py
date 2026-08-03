"""行业/主题数据集契约（架构 §3.2 equity_structure 与 PRD 主题模块）。

T03 负责填充；本模块只定义契约。
"""

from __future__ import annotations

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime


class SectorItem(ContractModel):
    """行业或主题条目。"""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    label_zh: str | None = None
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    percentile_5y: float | None = Field(default=None, ge=0.0, le=100.0)
    updated_at: UTCDateTime | None = None


class MemoryProxy(ContractModel):
    """存储周期代理（评审 P0-1：MVP 用美光/海力士/三星股价做存储周期代理）。"""

    label: str = Field(min_length=1)
    label_zh: str | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    note: str | None = None
    updated_at: UTCDateTime | None = None


class SectorsDataset(ContractModel):
    """sectors.json payload。"""

    sectors: list[SectorItem] = Field(default_factory=list)
    themes: list[SectorItem] = Field(default_factory=list)
    memory: MemoryProxy | None = None


class SectorsEnvelope(BaseEnvelope):
    payload: SectorsDataset
