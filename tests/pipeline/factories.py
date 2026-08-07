"""Synthetic data-contract factories for the pipeline test suite.

Why this module exists
----------------------
The pipeline test suite must never validate "whatever the last pipeline run happened to leave
on disk". Published artifacts cannot be regenerated without API keys and network access, they
cannot be made to *fail* on demand (so degradation behaviour is unprovable), and they go stale
the moment a contract gains a required field.

Every test therefore builds its own dataset from this module.

The seam
--------
``make_envelope(dataset, payload=None, **overrides)`` returns a plain JSON-ready ``dict`` (not a
Pydantic model) for any dataset in :data:`PAYLOAD_BUILDERS`. Plain dicts are deliberate: a test
must be able to construct an *invalid* document (out-of-range score, wrong type, missing field)
which a model instance would refuse to hold.

Two rules keep this maintainable as the contracts grow:

1. **Adding a required field is a one-line change.** Every builder is a flat dict literal of
   defaults merged with the caller's overrides. Add the field to the literal; every test that
   builds that dataset picks it up.
2. **Any field can be overridden or removed.** Pass ``field=value`` to change it, or
   ``field=REMOVE`` to drop the key entirely — that is how a test constructs the "required field
   is absent" case without hand-writing a whole document.

Determinism
-----------
All timestamps derive from :data:`DEFAULT_NOW`, a frozen instant. Tests pass ``now=DEFAULT_NOW``
into the validator, so freshness outcomes are a property of the fixture rather than of the wall
clock. Use :func:`ago` to build a document that is deliberately delayed or stale.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pipeline.schemas import registry
from pipeline.schemas.envelope import SCHEMA_VERSION

__all__ = [
    "DATASET_FILENAMES",
    "DEFAULT_NOW",
    "NOW_ISO",
    "PAYLOAD_BUILDERS",
    "REMOVE",
    "TODAY_ISO_DATE",
    "ago",
    "build_data_dir",
    "default_latest_files",
    "default_support_files",
    "iso",
    "make_analysis",
    "make_calendar_event",
    "make_calendar_payload",
    "make_crypto_asset",
    "make_crypto_payload",
    "make_dashboard_payload",
    "make_driver_contribution",
    "make_envelope",
    "make_equities_payload",
    "make_equity_asset",
    "make_evidence_ref",
    "make_facts",
    "make_fedwatch_history",
    "make_history_index",
    "make_history_rows",
    "make_macro_indicator",
    "make_macro_payload",
    "make_metadata_freshness",
    "make_metadata_schema_version",
    "make_metadata_sources",
    "make_news_item",
    "make_news_payload",
    "make_risk_dimension",
    "make_risk_indicator",
    "make_risk_payload",
    "make_sector_item",
    "make_sectors_payload",
    "write_json",
]


# --------------------------------------------------------------------------------------
# Override primitives
# --------------------------------------------------------------------------------------


class _Remove:
    """Sentinel: passing ``field=REMOVE`` deletes the key instead of overwriting it."""

    _instance: _Remove | None = None

    def __new__(cls) -> _Remove:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "REMOVE"

    def __bool__(self) -> bool:
        return False


REMOVE = _Remove()


def _build(defaults: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``overrides`` over ``defaults``.

    A value of :data:`REMOVE` deletes the key, which is how a test constructs a document that is
    missing a required field. Unknown keys are kept, which is how a test constructs a document
    with a forbidden extra field (the contracts use ``extra="forbid"``).
    """
    result: dict[str, Any] = dict(defaults)
    for key, value in overrides.items():
        if value is REMOVE:
            result.pop(key, None)
        else:
            result[key] = value
    return result


# --------------------------------------------------------------------------------------
# Frozen clock
# --------------------------------------------------------------------------------------

DEFAULT_NOW: datetime = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    """Format an aware datetime as the ISO 8601 UTC + Z string the contracts require."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(minutes: float, *, base: datetime = DEFAULT_NOW) -> str:
    """Return an ISO 8601 UTC timestamp ``minutes`` before ``base``.

    Freshness is graded against the expected interval in ``config/sources.yaml``:
    ``<= 1.5x`` fresh, ``<= 3x`` delayed, beyond that stale. ``ago`` is how a test asks for a
    specific one of those states instead of hoping real data happens to be in it.
    """
    return iso(base - timedelta(minutes=minutes))


NOW_ISO: str = iso(DEFAULT_NOW)
TODAY_ISO_DATE: str = DEFAULT_NOW.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------------------
# Shared leaf builders
# --------------------------------------------------------------------------------------


def make_evidence_ref(**overrides: Any) -> dict[str, Any]:
    """A single citable fact (``pipeline.schemas.factlayer.EvidenceRef``)."""
    return _build(
        {
            "dataset": "risk",
            "path": "payload.dimensions[0].score",
            "metric": "macro_dimension_score",
            "value": 64.0,
            "updated_at": NOW_ISO,
        },
        overrides,
    )


def make_macro_indicator(**overrides: Any) -> dict[str, Any]:
    """A single macro indicator (``pipeline.schemas.macro.MacroIndicator``)."""
    return _build(
        {
            "key": "dgs10",
            "label": "US 10Y Treasury Yield",
            "value": 4.25,
            "previous": 4.18,
            "change_1m": 0.07,
            "unit": "pct",
            "source": "FRED",
            "updated_at": NOW_ISO,
            "status": "fresh",
        },
        overrides,
    )


def make_equity_asset(**overrides: Any) -> dict[str, Any]:
    """A single equity card (``pipeline.schemas.equities.EquityAsset``)."""
    return _build(
        {
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "name_zh": "英伟达",
            "market": "US",
            "sector": "information_technology",
            "theme": ["ai_compute"],
            "price": 178.42,
            "currency": "USD",
            "change_1d": 1.12,
            "change_1w": 3.4,
            "change_1m": 8.6,
            "change_ytd": 24.9,
            "volume": 214_000_000.0,
            "market_cap": 4_350_000_000_000.0,
            "ma50_distance_pct": 4.1,
            "ma200_distance_pct": 12.7,
            "rsi14": 58.3,
            "percentile_1y": 92.5,
            "percentile_1y_obs": 250,
            "source": "yfinance",
            "updated_at": NOW_ISO,
            "is_proxy": False,
        },
        overrides,
    )


def make_crypto_asset(**overrides: Any) -> dict[str, Any]:
    """A single crypto asset (``pipeline.schemas.crypto.CryptoAsset``)."""
    return _build(
        {
            "symbol": "BTC",
            "name": "Bitcoin",
            "price": 68_400.0,
            "change_1d": -0.8,
            "change_1w": 2.3,
            "change_1m": 6.1,
            "market_cap": 1_350_000_000_000.0,
            "volume_24h": 31_000_000_000.0,
            "source": "coingecko",
            "updated_at": NOW_ISO,
        },
        overrides,
    )


def make_sector_item(**overrides: Any) -> dict[str, Any]:
    """A single sector or theme row (``pipeline.schemas.sectors.SectorItem``).

    No label/label_zh: since #102 (C-1) the payload carries the key and the numbers; the
    frontend renders t(themes.<key>) and check:i18n enforces the Chinese label exists.
    """
    return _build(
        {
            "key": "information_technology",
            "change_1d": 0.6,
            "change_1w": 1.9,
            "change_1m": 5.2,
            "percentile_1y": 81.0,
            "percentile_1y_obs": 250,
            "updated_at": NOW_ISO,
        },
        overrides,
    )


def make_news_item(**overrides: Any) -> dict[str, Any]:
    """A single news item (``pipeline.schemas.news.NewsItem``).

    ``id`` is the dedupe key and ``(title, source, published_at)`` is the secondary dedupe
    signature; both duplicate checks are driven by overriding those fields.
    """
    return _build(
        {
            "id": "e3b0c44298fc1c149afbf4c8996fb924",
            "title": "Treasury yields ease after softer payrolls print",
            "title_zh": "非农数据走软后美债收益率回落",
            "lang": "en",
            "source": "Reuters",
            "url": "https://example.invalid/news/treasury-yields-ease",
            "published_at": NOW_ISO,
            "categories": ["macro"],
            "assets": ["US10Y"],
            "importance": 72.0,
            "sentiment": "neutral",
            "summary": "Ten year yields fell as the payrolls report came in below consensus.",
            "summary_zh": "非农就业数据低于预期，十年期美债收益率下行。",
            "impact_window": "1d",
        },
        overrides,
    )


def make_calendar_event(**overrides: Any) -> dict[str, Any]:
    """A single calendar event (``pipeline.schemas.calendar.CalendarEvent``)."""
    return _build(
        {
            "id": "econ-CPI-2026-08-13",
            "type": "economic",
            "title": "US CPI (YoY)",
            "country": "US",
            "datetime": iso(DEFAULT_NOW + timedelta(days=9)),
            "importance": "high",
            "actual": None,
            "forecast": 2.7,
            "previous": 2.9,
            "unit": "pct",
            "related_assets": ["US10Y", "SPX"],
            "source": "fmp",
        },
        overrides,
    )


def make_risk_indicator(**overrides: Any) -> dict[str, Any]:
    """A single risk sub-indicator (``pipeline.schemas.risk.RiskIndicator``)."""
    return _build(
        {
            "key": "yield_curve_10y2y",
            "label": "10Y-2Y Spread",
            "value": 0.34,
            "percentile": 22.5,
            "z_score": -0.81,
            "risk_score": 64.0,
            "direction": "lower_is_riskier",
            "weight": 1.0,
            "source": "FRED",
            "updated_at": NOW_ISO,
            "status": "fresh",
            "is_proxy": False,
        },
        overrides,
    )


def make_risk_dimension(**overrides: Any) -> dict[str, Any]:
    """A single risk dimension (``pipeline.schemas.risk.RiskDimension``)."""
    return _build(
        {
            "key": "macro",
            "label": "Macro",
            "weight": 0.25,
            "effective_weight": 0.5,
            "score": 64.0,
            "indicators": [make_risk_indicator()],
            "coverage": 1.0,
            "trend": "rising",
        },
        overrides,
    )


def make_driver_contribution(**overrides: Any) -> dict[str, Any]:
    """A single top driver (``pipeline.schemas.risk.DriverContribution``)."""
    return _build(
        {
            "dimension_key": "macro",
            "indicator_key": "yield_curve_10y2y",
            "label": "10Y-2Y Spread",
            "contribution": 32.0,
            "change_1d": 0.9,
            "evidence_ref": make_evidence_ref(),
            "is_proxy": False,
            "discount": 1.0,
        },
        overrides,
    )


# --------------------------------------------------------------------------------------
# Per-dataset payload builders
# --------------------------------------------------------------------------------------


def make_macro_payload(**overrides: Any) -> dict[str, Any]:
    """``macro.json`` payload (``pipeline.schemas.macro.MacroDataset``)."""
    return _build(
        {
            "rates": [make_macro_indicator()],
            "credit": [make_macro_indicator(key="baa10y", label="BAA-10Y Credit Spread", unit="bps", value=182.0)],
            "inflation": [],
            "labor": [],
            "liquidity": [],
            "fx": [],
            "fedwatch": {
                "meeting_date": iso(DEFAULT_NOW + timedelta(days=40)),
                "effective_rate": 4.33,
                "implied_rate": 4.18,
                "probabilities": [
                    {"target_rate": 4.25, "probability": 0.72, "change_1d": 0.03},
                    {"target_rate": 4.0, "probability": 0.28, "change_1d": -0.03},
                ],
                "inferred_action": "hold",
                "change_1d": None,
                "status": "ready",
            },
        },
        overrides,
    )


def make_equities_payload(**overrides: Any) -> dict[str, Any]:
    """``equities.json`` payload (``pipeline.schemas.equities.EquitiesDataset``)."""
    return _build(
        {
            "assets": [
                make_equity_asset(),
                make_equity_asset(symbol="603986.SH", name="GigaDevice", name_zh="兆易创新", market="CN", currency="CNY", price=132.5),
            ],
        },
        overrides,
    )


def make_sectors_payload(**overrides: Any) -> dict[str, Any]:
    """``sectors.json`` payload (``pipeline.schemas.sectors.SectorsDataset``)."""
    return _build(
        {
            "sectors": [make_sector_item()],
            "themes": [make_sector_item(key="ai_compute")],
            "memory": {
                "label": "Memory Cycle Proxy",
                "label_zh": "存储周期代理",
                "change_1w": 2.4,
                "change_1m": 7.8,
                "note": "Proxied by Micron / Hynix / Samsung share prices.",
                "updated_at": NOW_ISO,
            },
        },
        overrides,
    )


def make_crypto_payload(**overrides: Any) -> dict[str, Any]:
    """``crypto.json`` payload (``pipeline.schemas.crypto.CryptoDataset``)."""
    return _build(
        {
            "assets": [make_crypto_asset(), make_crypto_asset(symbol="ETH", name="Ethereum", price=3_240.0)],
            "btc_dominance": 0.58,
            "stablecoin_mcap": 168_000_000_000.0,
            "market_cap_total": 2_360_000_000_000.0,
            "sentiment": "neutral",
        },
        overrides,
    )


def make_news_payload(**overrides: Any) -> dict[str, Any]:
    """``news.json`` payload (``pipeline.schemas.news.NewsDataset``).

    ``total`` follows ``items`` unless the caller pins it, so a test that appends an item does
    not accidentally create an unrelated inconsistency.
    """
    items = overrides.pop("items", None)
    if items is None:
        items = [
            make_news_item(),
            make_news_item(
                id="9f86d081884c7d659a2feaa0c55ad015",
                title="Fed officials signal patience on rate path",
                title_zh="美联储官员释放利率路径耐心信号",
                source="Bloomberg",
                url="https://example.invalid/news/fed-patience",
                importance=68.0,
            ),
        ]
    defaults: dict[str, Any] = {
        "items": items,
        "total": len(items) if isinstance(items, list) else 0,
        "updated_at": NOW_ISO,
    }
    return _build(defaults, overrides)


def make_calendar_payload(**overrides: Any) -> dict[str, Any]:
    """``calendar.json`` payload (``pipeline.schemas.calendar.CalendarDataset``)."""
    return _build(
        {
            "events": [
                make_calendar_event(),
                make_calendar_event(
                    id="earn-NVDA-2026-08-27",
                    type="earnings",
                    title="NVIDIA Q2 FY27 Earnings",
                    forecast=None,
                    previous=None,
                    unit=None,
                    related_assets=["NVDA"],
                ),
            ],
            "updated_at": NOW_ISO,
        },
        overrides,
    )


def make_risk_payload(**overrides: Any) -> dict[str, Any]:
    """``risk.json`` payload (``pipeline.schemas.risk.RiskModelResult``).

    ``total_score`` / dimension ``score`` / indicator ``risk_score`` are all range-checked twice
    (Pydantic ``Field`` bounds plus an explicit re-check in the validator); override any of them
    to exercise the out-of-range path.
    """
    return _build(
        {
            "model_version": SCHEMA_VERSION,
            "generated_at": NOW_ISO,
            "total_score": 62.5,
            "risk_level": "caution",
            "trend_1d": 0.8,
            "trend_1w": 2.1,
            "trend_1m": -1.4,
            # Indicator keys mirror the model.py registrations (#67): macro carries the four
            # real macro indicators (real_rate / curve / dollar / dgs10); liquidity_credit
            # carries the full credit set including ig_oas.
            "dimensions": [
                make_risk_dimension(
                    indicators=[
                        make_risk_indicator(key="real_rate_dfii10", label="10Y Real Rate", risk_score=64.0),
                        make_risk_indicator(key="yield_curve_10y2y", label="10Y-2Y Curve", risk_score=60.0),
                        make_risk_indicator(key="dollar_index", label="Dollar Index", risk_score=55.0),
                        make_risk_indicator(key="dgs10", label="10Y Yield", risk_score=52.0, direction="neutral"),
                    ]
                ),
                make_risk_dimension(
                    key="liquidity_credit",
                    label="Liquidity & Credit",
                    score=52.0,
                    indicators=[
                        make_risk_indicator(key="hy_oas", label="HY OAS", risk_score=55.0),
                        make_risk_indicator(key="ig_oas", label="IG OAS", risk_score=45.0),
                        make_risk_indicator(key="fed_balance_sheet", label="Fed Balance Sheet", risk_score=50.0, direction="neutral"),
                        make_risk_indicator(key="reverse_repo", label="Reverse Repo", risk_score=50.0, direction="neutral"),
                    ],
                    trend="flat",
                ),
                make_risk_dimension(
                    key="volatility",
                    label="Volatility",
                    score=61.0,
                    indicators=[make_risk_indicator(key="vix", label="VIX", risk_score=61.0, source="yfinance")],
                    trend="flat",
                ),
            ],
            "top_drivers": [make_driver_contribution()],
            "breadth": {
                "breadth_above_ma200": 0.65,
                "breadth_qualifying": 11,
                "breadth_considered": 18,
                "new_highs_ratio": 0.45,
                "new_lows_ratio": 0.2,
                "new_highs_qualifying": 8,
                "new_lows_qualifying": 4,
                "new_considered": 18,
                "small_cap_relative": -1.2,
                "semis_relative": 1.8,
                "is_proxy": True,
                "note": "MVP breadth uses index proxies (SPY/IWM/SOXX)",
            },
            "regime": "late_cycle",
            "regime_evidence": ["Curve steepening with credit spreads widening."],
            "confidence": 0.72,
            # Superset of the risk golden's confidence_factors (#73 conformance): the golden
            # carries data_quality/coverage/consistency; freshness is the factory's own extra.
            "confidence_factors": {"coverage": 1.0, "freshness": 0.9, "data_quality": 0.9, "consistency": 0.6},
            "disclaimer": "This indicator is a modeled estimate of market stress based on historical data and current market signals. It is not a definitive probability or investment advice.",
        },
        overrides,
    )


def make_dashboard_payload(**overrides: Any) -> dict[str, Any]:
    """``dashboard.json`` payload (``pipeline.schemas.dashboard.DashboardPayload``)."""
    return _build(
        {
            "risk": make_risk_payload(),
            "regime": "late_cycle",
            "top_drivers": [make_driver_contribution()],
            "cross_asset": [
                {"asset": "BTC", "category": "crypto", "change_1d": -0.8},
                {"asset": "NVDA", "category": "equity", "change_1d": 1.12},
            ],
            "catalysts": [{"id": "econ-CPI-2026-08-13", "title": "US CPI (YoY)"}],
            "sector_performance": [{"key": "information_technology", "change_1d": 0.6}],
        },
        overrides,
    )


#: Logical dataset name -> payload builder. Envelope datasets only.
PAYLOAD_BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "macro": make_macro_payload,
    "equities": make_equities_payload,
    "sectors": make_sectors_payload,
    "crypto": make_crypto_payload,
    "news": make_news_payload,
    "calendar": make_calendar_payload,
    "risk": make_risk_payload,
    "dashboard": make_dashboard_payload,
}

#: Logical dataset name -> published filename under ``latest/``.
DATASET_FILENAMES: dict[str, str] = {name: f"{name}.json" for name in PAYLOAD_BUILDERS}

#: Per-dataset envelope metadata that is not uniform across datasets.
_ENVELOPE_SOURCE: dict[str, Any] = {
    "macro": ["FRED"],
    "equities": ["yfinance", "akshare"],
    "sectors": ["yfinance"],
    "crypto": ["coingecko"],
    "news": ["rss"],
    "calendar": ["fmp"],
    "risk": "pipeline.risk",
    "dashboard": "pipeline.report",
}


def _dataset_key(dataset: str) -> str:
    """Accept either the logical name (``"news"``) or the filename (``"news.json"``)."""
    key = dataset[: -len(".json")] if dataset.endswith(".json") else dataset
    if key not in PAYLOAD_BUILDERS:
        raise KeyError(f"unknown dataset {dataset!r}; options: {sorted(PAYLOAD_BUILDERS)}")
    return key


def make_envelope(dataset: str, payload: Any = None, **overrides: Any) -> dict[str, Any]:
    """Build a minimal *valid* envelope document for ``dataset``.

    This is the seam the whole suite is built on. It returns a plain ``dict`` rather than a
    Pydantic model so that a caller can deliberately produce an invalid document.

    Args:
        dataset: Logical dataset name or published filename, e.g. ``"news"`` / ``"news.json"``.
        payload: Payload override. ``None`` means "use the dataset's default payload builder".
        **overrides: Envelope-level field overrides. Pass :data:`REMOVE` to drop a field.

    Returns:
        A JSON-serialisable envelope dict.

    Examples:
        A valid document::

            make_envelope("risk")

        An out-of-range risk score::

            make_envelope("risk", payload=make_risk_payload(total_score=150.0))

        A stale document::

            make_envelope("macro", generated_at=ago(minutes=60 * 24 * 30))

        A document missing a required envelope field::

            make_envelope("macro", data_quality=REMOVE)
    """
    key = _dataset_key(dataset)
    resolved_payload = PAYLOAD_BUILDERS[key]() if payload is None else payload
    # The factory's envelope carries a provenance descriptor (#65): the first candidate as
    # the resolved provider (the factory builds a clean, primary-provider document).
    source = _ENVELOPE_SOURCE[key]
    resolved_provider = source[0] if isinstance(source, list) else source
    defaults: dict[str, Any] = {
        "generated_at": NOW_ISO,
        "schema_version": SCHEMA_VERSION,
        "source": resolved_provider,
        "source_updated_at": NOW_ISO,
        "freshness_status": "fresh",
        "data_quality": 0.98,
        "provenance": {"provider": resolved_provider, "used_fallback": False, "from_cache": False},
        "payload": resolved_payload,
    }
    return _build(defaults, overrides)


# --------------------------------------------------------------------------------------
# Self-describing contract files (no envelope)
# --------------------------------------------------------------------------------------


def make_facts(**overrides: Any) -> dict[str, Any]:
    """``facts.json`` (``pipeline.schemas.factlayer.FactLayer``).

    Structure is a superset of the hand-written facts golden (#73 conformance): every key the
    golden carries must be producible, or a factory drift would silently narrow what the suite
    covers. ``data_freshness`` therefore names every dataset, ``evidence_index`` carries the
    three golden evidence ids, and the summaries cover the golden's fields.
    """
    return _build(
        {
            "generated_at": NOW_ISO,
            "schema_version": SCHEMA_VERSION,
            "data_freshness": {
                "macro": "fresh",
                "market": "fresh",
                "news": "fresh",
                "equities": "fresh",
                "sectors": "fresh",
                "crypto": "fresh",
                "calendar": "fresh",
                "risk": "fresh",
            },
            "risk": make_risk_payload(),
            "macro_summary": {
                "policy_rate": 4.33,
                "curve_10y2y": 0.34,
                "dgs10": 4.21,
                "real_rate_dfii10": 1.9,
                "change_1d_dgs10": 0.03,
            },
            "market_summary": {
                "spx_change_1d": 0.4,
                "nvda_change_1d": -2.1,
                "btc_change_1d": -0.8,
                "memory_theme_change_1d": -2.4,
            },
            "news_top": [
                {
                    "id": "e3b0c44298fc1c149afbf4c8996fb924",
                    "title": "Fed signals patience on rate cuts as inflation lingers",
                    "source": "CNBC",
                    "importance": 72.0,
                }
            ],
            "calendar_next7d": [
                {
                    "id": "econ-CPI-2026-08-13",
                    "type": "economic",
                    "title": "CPI YoY",
                    "datetime": iso(DEFAULT_NOW + timedelta(days=9)),
                    "importance": "high",
                }
            ],
            "evidence_index": {
                "macro_dimension_score": make_evidence_ref(),
                "ev_total_score": make_evidence_ref(
                    dataset="risk", path="payload.total_score", metric="total_score", value=52.3
                ),
                "ev_real_rate": make_evidence_ref(
                    dataset="macro", path="payload.rates[0].value", metric="real_rate_dfii10", value=1.9
                ),
                "ev_nvda_1d": make_evidence_ref(
                    dataset="equities", path="payload.assets[0].change_1d", metric="change_1d", value=-2.1
                ),
            },
        },
        overrides,
    )


#: Prose for the bilingual briefing. Only the language of the prose may differ between the two
#: files — every number must appear in both, which is what ``compare_bilingual`` enforces.
_ANALYSIS_PROSE: dict[str, dict[str, Any]] = {
    "zh-CN": {
        "summary": "总分 62.5，市场处于谨慎区间，信用利差走阔是主要压力来源。",
        "top_risk_driver": "10Y-2Y 利差压缩至 0.34，期限结构继续发出周期后段信号。",
        "supporting_signal": "投资级信用利差走阔 182 个基点。",
        "contradicting_signal": "风险资产维持强势，纳指相对高位仅回落 1.2。",
        "what_changed_today": "非农数据低于预期，十年期收益率下行。",
        "watch_next": "关注下一次 CPI 数据对利率路径的影响。",
        "bull_title": "温和降息情形",
        "bull_point": "若通胀回落至 2.7，政策路径将转向宽松。",
        "base_title": "区间震荡情形",
        "base_point": "总分维持在 62.5 附近，市场在谨慎区间内震荡。",
        "bear_title": "信用收缩情形",
        "bear_point": "若信用利差突破 250 个基点，风险将快速上行。",
    },
    "en": {
        "summary": "Total score 62.5 places the market in caution, driven mainly by widening credit spreads.",
        "top_risk_driver": "The 10Y-2Y spread compressed to 0.34, sustaining the late cycle signal.",
        "supporting_signal": "Investment grade credit spreads widened to 182 basis points.",
        "contradicting_signal": "Risk assets remain firm, with the Nasdaq only 1.2 below its high.",
        "what_changed_today": "Payrolls came in below consensus and ten year yields fell.",
        "watch_next": "Watch the next CPI print for its effect on the rate path.",
        "bull_title": "Gentle easing case",
        "bull_point": "If inflation cools to 2.7 the policy path turns accommodative.",
        "base_title": "Range bound case",
        "base_point": "The total score holds near 62.5 and the market oscillates within caution.",
        "bear_title": "Credit contraction case",
        "bear_point": "If credit spreads break 250 basis points risk rises quickly.",
    },
}


def make_analysis(*, language: str = "zh-CN", **overrides: Any) -> dict[str, Any]:
    """``analysis.{language}.json`` (``pipeline.schemas.analysis.AnalysisDataset``).

    ``language`` is keyword-only so that every field is overridable the same way
    (``make_analysis("en", language="fr")`` is a clean signature error, not
    ``TypeError: got multiple values``).

    The two languages produced by this builder are bilingually consistent by construction:
    identical ``market_state`` / ``market_regime`` / ``confidence`` / evidence refs, identical
    list lengths, and identical numbers inside every text field. Override one of those on a
    single side to build the inconsistency case.

    Structure is a superset of the hand-written analysis golden (#73 conformance): the golden
    carries evidence refs inside ``supporting_signals`` / ``contradicting_signals`` /
    ``bull_case`` and at the top level, so the factory's lists are non-empty too.
    """
    prose = _ANALYSIS_PROSE.get(language, _ANALYSIS_PROSE["en"])
    evidence = make_evidence_ref()
    return _build(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": NOW_ISO,
            "language": language,
            "market_state": "caution",
            "market_regime": "late_cycle",
            "summary": prose["summary"],
            "top_risk_drivers": [{"claim": prose["top_risk_driver"], "evidence_refs": [evidence]}],
            "supporting_signals": [{"claim": prose["supporting_signal"], "evidence_refs": [evidence]}],
            "contradicting_signals": [{"claim": prose["contradicting_signal"], "evidence_refs": [evidence]}],
            "what_changed_today": [prose["what_changed_today"]],
            "watch_next": [prose["watch_next"]],
            "bull_case": {"title": prose["bull_title"], "points": [prose["bull_point"]], "evidence_refs": [evidence]},
            "base_case": {"title": prose["base_title"], "points": [prose["base_point"]], "evidence_refs": []},
            "bear_case": {"title": prose["bear_title"], "points": [prose["bear_point"]], "evidence_refs": []},
            "confidence": 0.72,
            "evidence_refs": [evidence],
            "data_freshness": "fresh",
        },
        overrides,
    )


# --------------------------------------------------------------------------------------
# history/ metadata/ feeds/ builders
# --------------------------------------------------------------------------------------


def make_history_rows(days: int = 3, *, total_score: float = 62.5) -> list[dict[str, Any]]:
    """History slice rows: ``date`` must be ``YYYY-MM-DD`` and ``total_score`` must be 0-100."""
    return [
        {
            "date": (DEFAULT_NOW - timedelta(days=offset)).strftime("%Y-%m-%d"),
            "total_score": round(total_score - offset, 2),
        }
        for offset in reversed(range(days))
    ]


def make_history_index(**overrides: Any) -> dict[str, Any]:
    """``history/{series}/index.json`` — only required to parse."""
    return _build({"slices": ["30d", "90d", "daily"], "updated_at": NOW_ISO}, overrides)


def make_metadata_freshness(**overrides: Any) -> dict[str, Any]:
    """``metadata/freshness.json`` — one entry per registered dataset, with structured reasons.

    Built from the registry rather than a hand-picked trio, because the file's contract is now
    "every registered dataset, always present" (#89): a fixture that lists three keys cannot
    catch the regression where a dataset silently vanishes from the file.
    """
    return _build(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": NOW_ISO,
            "updated_at": NOW_ISO,
            "datasets": {
                key: {
                    "status": "fresh",
                    "reason": {"code": "ok", "detail": ""},
                    "updated_at": NOW_ISO,
                }
                for key in registry.CANONICAL_KEYS
            },
        },
        overrides,
    )


def make_metadata_sources(**overrides: Any) -> dict[str, Any]:
    """``metadata/sources.json`` — one entry per provider domain, agreeing with freshness.json.

    ``degraded`` is derived from the datasets a domain serves, so the fixture derives it the
    same way: a fixture in which the two files disagree would make the CI check that asserts
    they agree untestable.
    """
    return _build(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": NOW_ISO,
            "updated_at": NOW_ISO,
            "domains": {
                domain: {
                    "degraded": False,
                    "status": "fresh",
                    "reason": {"code": "ok", "detail": ""},
                    "datasets": list(keys),
                }
                for domain, keys in registry.DOMAIN_DATASETS.items()
            },
        },
        overrides,
    )


def make_metadata_schema_version(**overrides: Any) -> dict[str, Any]:
    """``metadata/schema-version.json`` — the validator warns unless ``schema_version`` exists."""
    return _build({"schema_version": SCHEMA_VERSION, "generated_at": NOW_ISO}, overrides)


def make_fedwatch_history(**overrides: Any) -> dict[str, Any]:
    """``feeds/fedwatch-history.json`` — only required to parse."""
    return _build(
        {
            "schema_version": SCHEMA_VERSION,
            "updated_at": NOW_ISO,
            "entries": [{"date": TODAY_ISO_DATE, "effective_rate": 4.33, "implied_rate": 4.18}],
        },
        overrides,
    )


# --------------------------------------------------------------------------------------
# Tree assembly
# --------------------------------------------------------------------------------------


def write_json(path: Path, obj: Any) -> Path:
    """Write ``obj`` as UTF-8 JSON, creating parent directories. Returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def make_news_translations(**overrides: Any) -> dict[str, Any]:
    """``news.zh-translations.json`` (``pipeline.schemas.news.NewsTranslationsDataset``).

    Produced by the AI automation, not the collection run — but it is a registered dataset, so
    the synthetic tree must contain it or the validator's "unknown/missing file" checks are
    exercised against an incomplete world.
    """
    return _build(
        {
            "items": [
                {
                    "id": "news-1",
                    "title": "Fed holds rates steady",
                    "summary": "The FOMC left the target range unchanged.",
                    "title_zh": "美联储维持利率不变",
                    "summary_zh": "联邦公开市场委员会维持目标区间不变。",
                }
            ],
            "updated_at": NOW_ISO,
        },
        overrides,
    )


def default_latest_files() -> dict[str, Any]:
    """Every file the validator looks for under ``latest/``, all valid."""
    files: dict[str, Any] = {
        filename: make_envelope(name) for name, filename in DATASET_FILENAMES.items()
    }
    files["facts.json"] = make_facts()
    files["analysis.zh-CN.json"] = make_analysis(language="zh-CN")
    files["analysis.en.json"] = make_analysis(language="en")
    files["news.zh-translations.json"] = make_news_translations()
    return files


def default_support_files() -> dict[str, Any]:
    """Every ``history/`` ``metadata/`` and ``feeds/`` file the validator looks for, all valid."""
    files: dict[str, Any] = {}
    for series in ("risk", "market"):
        for slice_name in ("30d", "90d", "daily"):
            files[f"history/{series}/{slice_name}.json"] = make_history_rows()
        files[f"history/{series}/index.json"] = make_history_index()
    files["metadata/freshness.json"] = make_metadata_freshness()
    files["metadata/sources.json"] = make_metadata_sources()
    files["metadata/schema-version.json"] = make_metadata_schema_version()
    files["feeds/fedwatch-history.json"] = make_fedwatch_history()
    return files


def build_data_dir(
    root: Path,
    *,
    latest: Mapping[str, Any] | None = None,
    support: Mapping[str, Any] | None = None,
) -> Path:
    """Write a complete, valid ``public/data``-shaped tree under ``root``.

    Validating the result yields zero errors *and* zero warnings, so any diagnostic a test
    observes is caused by that test's own override rather than by fixture drift.

    Args:
        root: Directory to create (the equivalent of ``public/data``).
        latest: Overrides for files under ``latest/``, keyed by filename. A value of
            :data:`REMOVE` omits the file — that is how the "required dataset missing" and
            "AI degraded mode" cases are built.
        support: Overrides for ``history/`` ``metadata/`` ``feeds/`` files, keyed by path
            relative to ``root``. :data:`REMOVE` omits the file.

    Returns:
        ``root``, so callers can inline it.
    """
    latest_files = _build(default_latest_files(), latest or {})
    support_files = _build(default_support_files(), support or {})

    (root / "latest").mkdir(parents=True, exist_ok=True)
    for filename, content in latest_files.items():
        write_json(root / "latest" / filename, content)
    for relative, content in support_files.items():
        write_json(root / relative, content)
    return root
