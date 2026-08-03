"""数据契约层（T02）。

Pydantic v2 模型全集，与前端 Zod / JSON Schema 三件套同构（架构 §1.1/§3.1）。
- 所有模型禁止隐式字段（extra="forbid"）、拒绝 NaN/Infinity（allow_inf_nan=False）。
- 时间一律 ISO 8601 UTC + Z；风险分 0-100、比率 0-1。
- 契约模型不包含任何采集/计算业务逻辑（那是 T03）。
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
from .crypto import CryptoAsset, CryptoDataset, CryptoEnvelope
from .dashboard import DashboardAsset, DashboardEnvelope, DashboardPayload
from .equities import EquitiesDataset, EquitiesEnvelope, EquityAsset
from .factlayer import EvidenceRef, FactLayer
from .macro import FedWatchRateProb, FedWatchSnapshot, MacroDataset, MacroEnvelope, MacroIndicator
from .news import NewsDataset, NewsEnvelope, NewsItem, NewsTranslation, NewsTranslationsDataset
from .risk import (
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

# 解析 risk.py 中 EvidenceRef 前向引用（factlayer ↔ risk 互相引用，见 risk.py 注释）
DriverContribution.model_rebuild(_types_namespace={"EvidenceRef": EvidenceRef})

__all__ = [
    "AnalysisDataset",
    "BaseEnvelope",
    "CalendarDataset",
    "CalendarEnvelope",
    "CalendarEvent",
    "CaseStatement",
    "ContractModel",
    "CryptoAsset",
    "CryptoDataset",
    "CryptoEnvelope",
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
