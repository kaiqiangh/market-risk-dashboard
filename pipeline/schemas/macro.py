"""Macro dataset contract (architecture §3.2 indicator mapping / review §3.1 FRED cornerstone).

payload structure: MacroIndicator lists grouped by business domain + FedWatch snapshot.
Filled by the T03 MacroCollector; this module only defines the contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, FreshnessStatus, UTCDateTime

MacroUnit = Literal["pct", "bps", "index", "usd", "ratio", "level"]


class MacroIndicator(ContractModel):
    """A single macro indicator (raw numeric storage, architecture §8.3)."""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | None = None
    previous: float | None = None
    change_1m: float | None = None
    unit: MacroUnit = "level"
    source: str = Field(min_length=1)
    updated_at: UTCDateTime | None = None
    status: FreshnessStatus = "fresh"


class FedWatchRateProb(ContractModel):
    """Probability of a target rate bucket (0-1)."""

    target_rate: float
    probability: float = Field(ge=0.0, le=1.0)
    change_1d: float | None = None


class FedWatchSnapshot(ContractModel):
    """CME FedWatch probability self-computed snapshot (architecture §1.6 frozen methodology)."""

    meeting_date: UTCDateTime | None = None
    effective_rate: float
    implied_rate: float
    probabilities: list[FedWatchRateProb] = Field(default_factory=list)
    inferred_action: Literal["hold", "hike", "cut", "insufficient_data"] | None = None
    change_1d: dict[str, float] | None = None
    status: Literal["accumulating", "ready"] = "accumulating"
    # Free settlement history is only ~5 trading days (review P0-1): "change vs a week ago" is
    # unavailable until the system has run for 7 full days; the frontend must show the
    # insufficient-data status instead of 0/empty.


class MacroDataset(ContractModel):
    """Macro dataset payload."""

    rates: list[MacroIndicator] = Field(default_factory=list)
    credit: list[MacroIndicator] = Field(default_factory=list)
    inflation: list[MacroIndicator] = Field(default_factory=list)
    labor: list[MacroIndicator] = Field(default_factory=list)
    liquidity: list[MacroIndicator] = Field(default_factory=list)
    fx: list[MacroIndicator] = Field(default_factory=list)
    fedwatch: FedWatchSnapshot | None = None


class MacroEnvelope(BaseEnvelope):
    """macro.json envelope (strongly typed payload)."""

    payload: MacroDataset
