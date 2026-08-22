"""Registry adapter for the Yahoo ZQ FedWatch futures source."""

from __future__ import annotations

import time

from pipeline.fedwatch.futures import fetch_contract_price, next_contract_codes
from pipeline.providers.base import BaseProvider, ProviderError, ProviderHealth


class FedWatchProvider(BaseProvider):
    name = "fedwatch"
    domain = "fedwatch"
    hosts = ("query1.finance.yahoo.com",)

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            code = next_contract_codes(count=1)[0]
            price = fetch_contract_price(code, timeout=5.0)
            return ProviderHealth(
                provider=self.name,
                ok=price is not None,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if price is not None else "empty futures price",
                checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001 - health() must not raise
            return ProviderHealth(
                provider=self.name,
                ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200],
                checked_at=None,
            )

    def get_contract_prices(self, codes: list[str]) -> dict[str, float | None]:
        prices: dict[str, float | None] = {}
        errors: list[str] = []
        for code in codes:
            try:
                prices[code] = fetch_contract_price(code)
            except ProviderError as exc:
                prices[code] = None
                errors.append(f"{code}: {exc}")
        if not any(price is not None for price in prices.values()):
            raise ProviderError("FedWatch futures unavailable: " + "; ".join(errors[:3]))
        return prices
