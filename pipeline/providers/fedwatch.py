"""Registry adapter for the Yahoo ZQ FedWatch futures source."""

from __future__ import annotations

from pipeline.fedwatch.futures import fetch_contract_price
from pipeline.providers.base import BaseProvider, ProviderError, ProviderHealth


class FedWatchProvider(BaseProvider):
    name = "fedwatch"
    domain = "fedwatch"
    hosts = ("query1.finance.yahoo.com",)

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True, error="probe deferred to collection", checked_at=None)

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
