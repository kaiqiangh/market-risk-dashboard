"""FMP free tier providers (architecture §1.3 frozen).

Since #83 the free tier lives on the ``/stable`` namespace — ``/api/v3/*`` returns 403
"Legacy Endpoint" for every path. Two providers:

- :class:`FmpProvider` — earnings calendar primary (field renames eps→epsActual, `time`
  dropped → session None; Nasdaq restores BMO/AMC, #94). 250 req/day is enough for one
  range call per day.
- :class:`FmpQuotesProvider` — quotes FALLBACK (replaces the retired Stooq provider,
  #100: Stooq now serves a JS proof-of-work challenge that TLS impersonation cannot
  defeat, verified live). `/stable/quote` answers with price/change/volume; the free tier
  carries no 1w/1m history, so those fields are honestly None and the #97 quote/history
  decoupling publishes the price without fabricating technicals.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pipeline.providers.base import (
    BaseProvider,
    ProviderError,
    ProviderHealth,
    QuoteResult,
)
from pipeline.utils import now_utc

# #83: the whole /api/v3 namespace is retired — FMP_BASE moved to /stable and the
# earnings endpoint renamed (earning_calendar → earnings-calendar). Both verified live.
FMP_BASE = "https://financialmodelingprep.com/stable"
EARNINGS_ENDPOINT = f"{FMP_BASE}/earnings-calendar"


class FmpProvider(BaseProvider):
    name = "fmp"
    domain = "calendar"
    hosts = ("financialmodelingprep.com",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.fmp_api_key
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0)

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(provider=self.name, ok=False, error="missing DATA_FMP_API_KEY", checked_at=None)
        started = time.monotonic()
        try:
            events = self.get_earnings_calendar(_today(), _today())
            ok = isinstance(events, list)
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "bad payload", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def get_earnings_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        """Earnings rows in the shared normalized shape (symbol/date/estimates/session).

        ``session`` is always None here — the stable payload dropped ``time`` (#83); the
        Nasdaq fallback supplies BMO/AMC. Retries live in ProviderRegistry.call (#103/E-3).
        """
        if not self.api_key:
            raise ProviderError("FMP: missing DATA_FMP_API_KEY (local .env)")

        resp = self._client.get(
            EARNINGS_ENDPOINT,
            params={"from": start, "to": end, "apikey": self.api_key},
        )
        if resp.status_code != 200:
            # #103/S-1: one error boundary — classification + redaction (from_http).
            raise ProviderError.from_http("FMP calendar", resp)
        data = resp.json()
        if not isinstance(data, list):
            raise ProviderError("FMP calendar unexpected payload")

        items: list[dict[str, Any]] = []
        for row in data:
            symbol = str(row.get("symbol", "")).upper()
            date = str(row.get("date", ""))
            if not symbol or not date:
                continue
            items.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "eps_estimate": _f(row.get("epsEstimated")),
                    # stable renamed `eps` → `epsActual` (#83) — reading the old key would
                    # silently produce eps_actual=None forever.
                    "eps_actual": _f(row.get("epsActual")),
                    "revenue_estimate": _f(row.get("revenueEstimated")),
                    "revenue_actual": _f(row.get("revenueActual")),
                    "session": None,
                }
            )
        return items


class FmpQuotesProvider(BaseProvider):
    """Quotes fallback (domain quotes, priority 2) — `/stable/quote` (#100).

    Replaces Stooq (JS challenge, unrecoverable). Quote-only on the free tier: price,
    change_1d and volume are real; 1w/1m/history are honestly None (the collector's
    #97 decoupling publishes the price with None technicals instead of dropping it).
    """

    name = "fmp_quotes"
    domain = "quotes"
    hosts = ("financialmodelingprep.com",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.fmp_api_key
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0)

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(provider=self.name, ok=False, error="missing DATA_FMP_API_KEY", checked_at=None)
        started = time.monotonic()
        try:
            quote = self.get_quote("SPY")
            ok = quote.price is not None
            return ProviderHealth(
                provider=self.name, ok=bool(ok),
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "empty quote", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def get_quote(self, symbol: str) -> QuoteResult:
        if not self.api_key:
            raise ProviderError("FMP quotes: missing DATA_FMP_API_KEY (local .env)")
        resp = self._client.get(
            f"{FMP_BASE}/quote",
            params={"symbol": symbol, "apikey": self.api_key},
        )
        if resp.status_code != 200:
            raise ProviderError.from_http("FMP quote", resp)
        data = resp.json()
        if not isinstance(data, list) or not data:
            raise ProviderError(f"FMP quote {symbol}: unexpected payload")
        row = data[0]
        price = _f(row.get("price"))
        if price is None:
            raise ProviderError(f"FMP quote {symbol}: no price")
        change_1d = _f(row.get("changePercentage"))
        return QuoteResult(
            symbol=symbol,
            price=price,
            change_1d=change_1d,
            change_1w=None,
            change_1m=None,
            volume=_f(row.get("volume")),
            source="fmp",
            provider=self.name,
            updated_at=now_utc(),
            is_proxy=False,
        )

    # NOTE: no get_history — the free tier has no stable history endpoint (verified live,
    # #100); the collector's quote/history decoupling (#97) publishes the quote with None
    # technicals rather than dropping the symbol.


def _f(value) -> float | None:
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
