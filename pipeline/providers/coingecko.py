"""Crypto primary source: CoinGecko API (architecture §1.3 frozen; Demo key is enough for a few dozen calls per day).

Direct httpx connection; Demo key read from .env (DATA_COINGECKO_API_KEY).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from pipeline.providers._util import _f
from pipeline.providers.base import (
    BaseProvider,
    ProviderError,
    ProviderHealth,
)
from pipeline.utils import now_utc

CG_BASE = "https://api.coingecko.com/api/v3"


class CoinGeckoProvider(BaseProvider):
    name = "coingecko"
    domain = "crypto"
    hosts = ("api.coingecko.com",)
    requires_api_key = True

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.coingecko_api_key
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0)
        # #102 (D-8): the coin list and id→symbol map derive from the universe's crypto
        # pool (symbol + name → coingecko id), not a hardcoded "bitcoin,ethereum,solana".
        from pipeline.universe import AssetUniverse

        crypto = AssetUniverse.load(self.settings).crypto
        self.cg_ids: list[str] = [a.name.lower() for a in crypto]
        self.cg_id_map: dict[str, str] = {a.name.lower(): a.symbol for a in crypto}

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"x-cg-demo-api-key": self.api_key}
        return {}

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        if not self.api_key:
            return ProviderHealth(provider=self.name, ok=False, error="missing DATA_COINGECKO_API_KEY", checked_at=None)
        try:
            data = self._get_simple_price()
            ok = bool(data)
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "empty response", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        def _fetch() -> Any:
            resp = self._client.get(f"{CG_BASE}{path}", params=params, headers=self._headers())
            if resp.status_code != 200:
                # #103/E-3: classification (429 → rate_limited) + redaction at one boundary.
                raise ProviderError.from_exception(
                    httpx.HTTPStatusError(
                        f"CoinGecko HTTP {resp.status_code}", request=resp.request, response=resp
                    ),
                    detail=f"CoinGecko {path}: HTTP {resp.status_code}",
                )
            data = resp.json()
            if not isinstance(data, (dict, list)):
                raise ProviderError("CoinGecko unexpected payload")
            return data

        # #103/E-3: retries live in ProviderRegistry.call, not here.
        return _fetch()

    def _get_simple_price(self) -> dict[str, Any]:
        data = self._get("/simple/price", {"ids": ",".join(self.cg_ids), "vs_currencies": "usd"})
        if not isinstance(data, dict):
            raise ProviderError("CoinGecko simple price returned an unexpected payload")
        return data

    def get_crypto_market(self) -> dict[str, Any]:
        """Return {assets: [...], btc_dominance, market_cap_total}."""
        if not self.api_key:
            raise ProviderError("CoinGecko: missing DATA_COINGECKO_API_KEY")
        market_data = self._get(
            "/coins/markets",
            {
                "vs_currency": "usd",
                "ids": ",".join(self.cg_ids),
                "price_change_percentage": "24h,7d,30d",
            },
        )
        if not isinstance(market_data, list):
            raise ProviderError("CoinGecko market data returned an unexpected payload")

        assets: list[dict[str, Any]] = []
        for detail in market_data:
            if not isinstance(detail, dict):
                continue
            symbol = self.cg_id_map.get(str(detail.get("id", "")).lower())
            if symbol is None:
                continue
            price = detail.get("current_price")
            if price is None:
                continue
            assets.append(
                {
                    "symbol": symbol,
                    "name": detail.get("name") or symbol,
                    "price": _f(price),
                    "change_1d": _f(detail.get("price_change_percentage_24h")),
                    "change_1w": _f(detail.get("price_change_percentage_7d")),
                    "change_1m": _f(detail.get("price_change_percentage_30d")),
                    "market_cap": _f(detail.get("market_cap")),
                    "volume_24h": _f(detail.get("total_volume")),
                    "source": "coingecko",
                    "updated_at": now_utc(),
                }
            )

        global_data = self._get("/global", {})
        gd = global_data.get("data", {})
        return {
            "assets": assets,
            "btc_dominance": _ratio01(gd.get("market_cap_percentage", {}).get("btc")),
            "stablecoin_mcap": _f(gd.get("stablecoin_market_cap")),
            "market_cap_total": _f(gd.get("total_market_cap", {}).get("usd")),
            "sentiment": None,
        }
def _ratio01(value) -> float | None:
    """CoinGecko percentage (e.g. 56.23) → 0-1 ratio."""
    f = _f(value)
    if f is None:
        return None
    return round(max(0.0, min(1.0, f / 100.0)), 6)
