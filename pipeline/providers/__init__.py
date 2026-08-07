"""Providers package: factory functions for centralized registration (architecture §1.4 ProviderRegistry)."""

from __future__ import annotations

from pipeline.config.models import ConfigError
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
from pipeline.settings import Settings

#: config name → provider class. The name in config/sources.yaml:providers is the class
#: identity; the class's own ``domain`` attribute must match the config group it is listed
#: under, or the factory fails loudly (a provider in the wrong domain would silently sit in
#: a degradation chain it does not belong to).
_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "yfinance": YahooProvider,
    "stooq": StooqProvider,
    "fred": FredProvider,
    "coingecko": CoinGeckoProvider,
    "fmp": FmpProvider,
    "yfinance_calendar": YahooCalendarProvider,
    "akshare": AkshareProvider,
    "rss_news": RssNewsProvider,
}


def build_default_providers(settings=None) -> list[BaseProvider]:
    """Build Providers from config/sources.yaml:providers — order, priority and enabled (C-3).

    The degradation chain used to be a hardcoded list here; it is now declared in config.
    ``enabled: false`` entries are inert (never constructed — `binance_public` is a
    deliberate not-yet-implemented placeholder). An *enabled* entry naming an unknown
    provider, or a provider whose domain disagrees with its config group, raises
    :class:`~pipeline.config.models.ConfigError` before any provider is constructed.
    """
    s = settings or Settings()
    cfg = s.load_sources_config()
    providers: list[BaseProvider] = []
    for domain, entries in cfg.providers.items():
        for entry in sorted(entries, key=lambda e: e.priority):
            if not entry.enabled:
                continue
            cls = _PROVIDER_CLASSES.get(entry.name)
            if cls is None:
                raise ConfigError(
                    f"sources.yaml:providers.{domain}: unknown provider {entry.name!r} "
                    f"(implemented: {', '.join(sorted(_PROVIDER_CLASSES))})"
                )
            provider = cls(s)
            if provider.domain != domain:
                raise ConfigError(
                    f"sources.yaml:providers.{domain}: {entry.name!r} is a "
                    f"{provider.domain!r} provider, not {domain!r}"
                )
            provider.priority = entry.priority
            providers.append(provider)
    return providers


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
