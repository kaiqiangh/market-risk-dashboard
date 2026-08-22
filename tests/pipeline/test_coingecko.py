"""CoinGecko bulk-market request contract (#193)."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx

from pipeline.providers.coingecko import CG_BASE, CoinGeckoProvider
from pipeline.settings import Settings


def test_crypto_market_uses_one_bulk_market_request(tmp_path: Path) -> None:
    provider = CoinGeckoProvider(Settings(_env_file=None, artifacts_dir=tmp_path))
    provider.api_key = "test-key"
    with respx.mock:
        markets = respx.get(f"{CG_BASE}/coins/markets").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "bitcoin",
                        "symbol": "btc",
                        "name": "Bitcoin",
                        "current_price": 100.0,
                        "price_change_percentage_24h": 1.0,
                        "price_change_percentage_7d": 2.0,
                        "price_change_percentage_30d": 3.0,
                        "market_cap": 1000.0,
                        "total_volume": 100.0,
                    }
                ],
            )
        )
        global_data = respx.get(f"{CG_BASE}/global").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "market_cap_percentage": {"btc": 50.0},
                        "stablecoin_market_cap": 200.0,
                        "total_market_cap": {"usd": 2000.0},
                    }
                },
            )
        )
        result = provider.get_crypto_market()

    assert markets.call_count == 1
    assert global_data.call_count == 1
    assert result["assets"][0]["symbol"] == "BTC"
    assert result["assets"][0]["change_1m"] == 3.0
