"""Data contract layer (T02).

Complete set of Pydantic v2 models, isomorphic to the frontend Zod / JSON Schema three artifacts
(architecture §1.1/§3.1).
- All models forbid implicit fields (extra="forbid") and reject NaN/Infinity (allow_inf_nan=False).
- Times are always ISO 8601 UTC + Z; risk scores 0-100, ratios 0-1.
- Contract models contain no collection/computation business logic (that is T03).
"""

from .analysis import AnalysisDataset, AnalysisLineage, CaseStatement, SignalClaim
from .calendar import CalendarDataset, CalendarEnvelope, CalendarEvent
from .commodities import CommoditiesDataset, CommoditiesEnvelope, CommodityAsset
from .crypto import CryptoAsset, CryptoDataset, CryptoEnvelope
from .dashboard import DashboardAsset, DashboardEnvelope, DashboardPayload, DashboardSector
from .envelope import (
    BaseEnvelope,
    ContractModel,
    FreshnessStatus,
    UTCDateTime,
    validate_utc_datetime,
)
from .equities import EquitiesDataset, EquitiesEnvelope, EquityAsset
from .factlayer import EvidenceRef, FactLayer
from .macro import FedWatchRateProb, FedWatchSnapshot, MacroDataset, MacroEnvelope, MacroIndicator
from .metadata import ProviderResolution
from .news import NewsDataset, NewsEnvelope, NewsItem, NewsTranslation, NewsTranslationsDataset
from .risk import (
    BreadthSnapshot,
    CrossAssetSignal,
    DriverContribution,
    MarketRegime,
    RiskCalibrationStatus,
    RiskDimension,
    RiskDimensionKey,
    RiskDirection,
    RiskEnvelope,
    RiskEvidenceState,
    RiskIndicator,
    RiskLevel,
    RiskModelResult,
)
from .sectors import MemoryProxy, SectorItem, SectorsDataset, SectorsEnvelope

# Resolve the EvidenceRef forward reference in risk.py (factlayer ↔ risk mutually reference; see risk.py comment)
DriverContribution.model_rebuild(_types_namespace={"EvidenceRef": EvidenceRef})

__all__ = [
    "AnalysisDataset",
    "AnalysisLineage",
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
    "CrossAssetSignal",
    "DashboardAsset",
    "DashboardEnvelope",
    "DashboardPayload",
    "DashboardSector",
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
    "ProviderResolution",
    "NewsDataset",
    "NewsEnvelope",
    "NewsItem",
    "NewsTranslation",
    "NewsTranslationsDataset",
    "RiskDimension",
    "RiskDimensionKey",
    "RiskDirection",
    "RiskCalibrationStatus",
    "RiskEvidenceState",
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
