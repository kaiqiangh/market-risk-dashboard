"""日历数据集契约（经济日历 + 财报日历，架构 §1.3 / §3.5）。

T03 CalendarCollector 负责填充；本模块只定义契约。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

EventType = Literal["economic", "earnings"]
EventImportance = Literal["high", "medium", "low"]


class CalendarEvent(ContractModel):
    id: str = Field(min_length=1, description="稳定去重键，如 econ-CPI-2026-08-13")
    type: EventType
    title: str = Field(min_length=1)
    country: str | None = None
    datetime: UTCDateTime
    importance: EventImportance = "medium"
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    unit: str | None = None
    related_assets: list[str] = Field(default_factory=list)
    source: str = Field(min_length=1)


class CalendarDataset(ContractModel):
    """calendar.json payload。"""

    events: list[CalendarEvent] = Field(default_factory=list)
    updated_at: UTCDateTime | None = None


class CalendarEnvelope(BaseEnvelope):
    payload: CalendarDataset
