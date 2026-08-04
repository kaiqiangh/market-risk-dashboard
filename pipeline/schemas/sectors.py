"""Sectors/themes dataset contract (architecture §3.2 equity_structure and PRD themes module).

Filled by T03; this module only defines the contract.
"""

from __future__ import annotations

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime


class SectorItem(ContractModel):
    """Sector or theme entry."""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    label_zh: str | None = None
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    percentile_1y: float | None = Field(default=None, ge=0.0, le=100.0, description="percentile within the ~1y history window (#70)")
    percentile_1y_obs: int = Field(default=0, ge=0, description="observations behind the percentile (#70)")
    updated_at: UTCDateTime | None = None


class MemoryProxy(ContractModel):
    """Memory cycle proxy (review P0-1: MVP uses Micron/Hynix/Samsung share prices as a memory cycle proxy)."""

    label: str = Field(min_length=1)
    label_zh: str | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    note: str | None = None
    updated_at: UTCDateTime | None = None


class SectorsDataset(ContractModel):
    """sectors.json payload."""

    sectors: list[SectorItem] = Field(default_factory=list)
    themes: list[SectorItem] = Field(default_factory=list)
    memory: MemoryProxy | None = None


class SectorsEnvelope(BaseEnvelope):
    payload: SectorsDataset
