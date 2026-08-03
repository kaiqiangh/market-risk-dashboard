"""资产池加载（架构 §8：config/universe.yaml 为唯一事实源）。

T03 起被 Collectors/RiskModel 使用；前端 src/config/universe.ts 为展示镜像。
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
    theme: list[str]
    market: str  # "US" | "CN" | "CRYPTO" | "METAL" | "OIL"
    extra: dict[str, Any] = field(default_factory=dict)


class AssetUniverse:
    """从 config/universe.yaml 加载的资产池。"""

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
                    theme=list(entry.get("theme", [])),
                    market=market,
                )
            )
        return assets

    def all_equities(self) -> list[Asset]:
        """美股 + A 股（EquityAsset 使用的全部股票）。"""
        return [*self.us_equities, *self.a_share_memory]

    def symbols(self, market: str | None = None) -> list[str]:
        assets = self.all_equities()
        if market:
            assets = [a for a in assets if a.market == market]
        return [a.symbol for a in assets]

    @classmethod
    def load(cls, settings: Settings | None = None) -> "AssetUniverse":
        s = settings or Settings()
        return cls(s.load_universe())
