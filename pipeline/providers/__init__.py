"""Providers package: factory functions for centralized registration (architecture §1.4 ProviderRegistry)."""

from __future__ import annotations

from pipeline.providers.akshare_provider import AkshareProvider
from pipeline.providers.base import (
    BaseProvider,
    HistoryResult,
    ProviderError,
    ProviderHealth,
    ProviderRegistry,
    QuoteResult,
    retry_with_backoff,
)
from pipeline.providers.coingecko import CoinGeckoProvider
from pipeline.providers.fmp import FmpProvider
from pipeline.providers.fred import FredProvider
from pipeline.providers.rss_news import RssNewsProvider
from pipeline.providers.stooq import StooqProvider
from pipeline.providers.yahoo import YahooCalendarProvider, YahooProvider


def build_default_providers(settings=None) -> list[BaseProvider]:
    """Build all Providers (registration order determines the degradation chain)."""
    return [
        YahooProvider(settings),
        StooqProvider(settings),
        FredProvider(settings),
        CoinGeckoProvider(settings),
        FmpProvider(settings),
        YahooCalendarProvider(settings),
        AkshareProvider(settings),
        RssNewsProvider(settings),
    ]


def build_registry(settings=None) -> ProviderRegistry:
    """Build a Registry with all Providers registered."""
    registry = ProviderRegistry(settings)
    registry.register_all(build_default_providers(settings))
    return registry


__all__ = [
    "AkshareProvider",
    "BaseProvider",
    "CoinGeckoProvider",
    "FmpProvider",
    "FredProvider",
    "HistoryResult",
    "ProviderError",
    "ProviderHealth",
    "ProviderRegistry",
    "QuoteResult",
    "RssNewsProvider",
    "StooqProvider",
    "YahooCalendarProvider",
    "YahooProvider",
    "build_default_providers",
    "build_registry",
    "retry_with_backoff",
]
