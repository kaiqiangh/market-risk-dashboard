"""Data contract layer (T02).

Complete set of Pydantic v2 models, isomorphic to the frontend Zod / JSON Schema three artifacts
(architecture §1.1/§3.1).
- All models forbid implicit fields (extra="forbid") and reject NaN/Infinity (allow_inf_nan=False).
- Times are always ISO 8601 UTC + Z; risk scores 0-100, ratios 0-1.
- Contract models contain no collection/computation business logic (that is T03).
"""

from .envelope import (
    BaseEnvelope,
    ContractModel,
    FreshnessStatus,
    UTCDateTime,
    validate_utc_datetime,
)
from .analysis import AnalysisDataset, CaseStatement, SignalClaim
from .calendar import CalendarDataset, CalendarEnvelope, CalendarEvent
from .commodities import CommoditiesDataset, CommoditiesEnvelope, CommodityAsset
from .crypto import CryptoAsset, CryptoDataset, CryptoEnvelope
from .dashboard import DashboardAsset, DashboardEnvelope, DashboardPayload
from .equities import EquitiesDataset, EquitiesEnvelope, EquityAsset
from .factlayer import EvidenceRef, FactLayer
from .macro import FedWatchRateProb, FedWatchSnapshot, MacroDataset, MacroEnvelope, MacroIndicator
from .news import NewsDataset, NewsEnvelope, NewsItem, NewsTranslation, NewsTranslationsDataset
from .risk import (
    BreadthSnapshot,
    DriverContribution,
    MarketRegime,
    RiskDimension,
    RiskDimensionKey,
    RiskDirection,
    RiskEnvelope,
    RiskIndicator,
    RiskLevel,
    RiskModelResult,
)
from .sectors import MemoryProxy, SectorItem, SectorsDataset, SectorsEnvelope

# Resolve the EvidenceRef forward reference in risk.py (factlayer ↔ risk mutually reference; see risk.py comment)
DriverContribution.model_rebuild(_types_namespace={"EvidenceRef": EvidenceRef})

__all__ = [
    "AnalysisDataset",
    "BaseEnvelope",
    "CalendarDataset",
    "CalendarEnvelope",
    "CalendarEvent",
    "CaseStatement",
    "CommoditiesDataset",
    "CommoditiesEnvelope",
    "CommodityAsset",
    "ContractModel",
    "CryptoAsset",
    "CryptoDataset",
    "CryptoEnvelope",
    "BreadthSnapshot",
    "DashboardAsset",
    "DashboardEnvelope",
    "DashboardPayload",
    "DriverContribution",
    "EquitiesDataset",
    "EquitiesEnvelope",
    "EquityAsset",
    "EvidenceRef",
    "FactLayer",
    "FedWatchRateProb",
    "FedWatchSnapshot",
    "FreshnessStatus",
    "MacroDataset",
    "MacroEnvelope",
    "MacroIndicator",
    "MarketRegime",
    "MemoryProxy",
    "NewsDataset",
    "NewsEnvelope",
    "NewsItem",
    "NewsTranslation",
    "NewsTranslationsDataset",
    "RiskDimension",
    "RiskDimensionKey",
    "RiskDirection",
    "RiskEnvelope",
    "RiskIndicator",
    "RiskLevel",
    "RiskModelResult",
    "SectorItem",
    "SectorsDataset",
    "SectorsEnvelope",
    "SignalClaim",
    "UTCDateTime",
    "validate_utc_datetime",
]
