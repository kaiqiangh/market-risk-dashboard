"""Asset universe loading (architecture §8: config/universe.yaml is the single source of truth).

Used by Collectors/RiskModel since T03; the frontend src/config/universe.ts is a display mirror.

#102 (D-8): universe entries carry no ``theme`` tag — theme membership lives in
config/themes.yaml (theme → constituents), so the reference runs theme → symbol only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.settings import Settings


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    name_zh: str | None
    sector: str
    market: str  # "US" | "CN" | "CRYPTO" | "METAL" | "OIL"
    extra: dict[str, Any] = field(default_factory=dict)


class AssetUniverse:
    """Asset universe loaded from config/universe.yaml."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.version: str = str(raw.get("version", "1.0.0"))
        self.us_equities: list[Asset] = self._parse(raw.get("us_equities", []), "US")
        self.a_share_memory: list[Asset] = self._parse(raw.get("a_share_memory", []), "CN")
        self.crypto: list[Asset] = self._parse(raw.get("crypto", []), "CRYPTO")
        self.metals: list[Asset] = self._parse(raw.get("metals", []), "METAL")
        self.oil: list[Asset] = self._parse(raw.get("oil", []), "OIL")

    @staticmethod
    def _parse(entries: list[dict[str, Any]], market: str) -> list[Asset]:
        assets: list[Asset] = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("symbol"):
                continue
            assets.append(
                Asset(
                    symbol=str(entry["symbol"]).upper(),
                    name=str(entry.get("name", entry["symbol"])),
                    name_zh=entry.get("name_zh"),
                    sector=str(entry.get("sector", "other")),
                    market=market,
                )
            )
        return assets

    def all_equities(self) -> list[Asset]:
        """US + A-share equities (all stocks used by EquityAsset)."""
        return [*self.us_equities, *self.a_share_memory]

    def symbols(self, market: str | None = None) -> list[str]:
        assets = self.all_equities()
        if market:
            assets = [a for a in assets if a.market == market]
        return [a.symbol for a in assets]

    def news_aliases(self) -> dict[str, list[str]]:
        """symbol → search aliases for news asset hits, derived from the universe (D-8).

        Each symbol matches its ticker (lowercased), its English name and its Chinese
        name — the shape of the hardcoded table this replaces (``collectors/news.py``).
        """
        aliases: dict[str, list[str]] = {}
        for asset in [*self.all_equities(), *self.crypto]:
            tokens = [asset.symbol.lower(), asset.name.lower()]
            if asset.name_zh:
                tokens.append(asset.name_zh)
            aliases[asset.symbol] = tokens
        return aliases

    @classmethod
    def load(cls, settings: Settings | None = None) -> "AssetUniverse":
        s = settings or Settings()
        cfg = s.load_universe_config()
        return cls(cfg.model_dump())
