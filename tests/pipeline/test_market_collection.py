"""Market history planning and request telemetry (#144)."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.collectors.market import MarketCollector
from pipeline.providers.base import HistoryResult, ProviderError
from pipeline.schemas import CommoditiesDataset, CryptoDataset, EquitiesDataset, SectorsDataset
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse


class _HistoryRegistry:
    def __init__(self, *, empty_symbols: set[str] | None = None, failing_symbols: set[str] | None = None) -> None:
        self.empty_symbols = empty_symbols or set()
        self.failing_symbols = failing_symbols or set()
        self.degraded_domains: set[str] = set()
        self.calls: list[tuple[str, str, str, str]] = []

    def resolved_provider(self, domain: str):
        return {"provider": "test-provider", "used_fallback": False, "from_cache": False}

    def call(self, domain: str, method: str, key: str, args=(), kwargs=None):
        assert method == "get_history"
        symbol, period = str(args[0]), str(args[1])
        self.calls.append((domain, symbol, period, key))
        if symbol in self.failing_symbols:
            raise ProviderError(f"{symbol}: upstream unavailable")
        rows = [] if symbol in self.empty_symbols else [
            {"date": "2026-08-05", "close": 100.0},
            {"date": "2026-08-06", "close": 101.0},
        ]
        return {
            "result": HistoryResult(symbol=symbol, provider="test-provider", rows=rows, period=period),
            "meta": {
                "provider": "test-provider",
                "used_fallback": symbol == "SPY",
                "from_cache": False,
                "degraded": symbol == "SPY",
            },
        }


def _collector(registry: _HistoryRegistry, tmp_path: Path) -> MarketCollector:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)
    return MarketCollector(registry, AssetUniverse.load(settings), settings)


def test_history_plan_is_stable_deduplicated_and_covers_consumers(tmp_path: Path) -> None:
    collector = _collector(_HistoryRegistry(), tmp_path)

    first = collector._build_history_plan()
    second = collector._build_history_plan()
    keys = [(item.domain, item.symbol, item.period) for item in first]

    assert first == second
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert ("quotes", "SPY", "1y") in keys
    assert ("quotes", "XLY", "1y") in keys
    assert ("quotes", "HYG", "1y") in keys
    assert any(item.symbol == "NVDA" and "equity_card" in item.consumers for item in first)
    assert any("themes" in item.consumers for item in first)


def test_history_plan_makes_one_bounded_request_per_target(tmp_path: Path) -> None:
    registry = _HistoryRegistry()
    collector = _collector(registry, tmp_path)
    plan = collector._build_history_plan()

    collector._collect_history_plan()
    requested = [(domain, symbol, period) for domain, symbol, period, _ in registry.calls]

    assert len(registry.calls) == len(plan)
    assert len(requested) == len(set(requested))
    assert collector._collection_telemetry()["duplicate_request_keys"] == 0
    assert collector._collection_telemetry()["history_request_count"] == len(plan)
    assert all(item["requested"] == 1 for item in collector._history_telemetry)


def test_history_telemetry_reports_missing_and_degraded_without_provider_errors(tmp_path: Path) -> None:
    registry = _HistoryRegistry(empty_symbols={"XLY"}, failing_symbols={"HYG"})
    collector = _collector(registry, tmp_path)

    collector._collect_history_plan()
    telemetry = collector._collection_telemetry()
    payload = json.dumps(telemetry, ensure_ascii=False)

    assert any(item["symbol"] == "XLY" and item["status"] == "empty" for item in telemetry["missing_inputs"])
    assert any(item["symbol"] == "HYG" and item["status"] == "missing" for item in telemetry["missing_inputs"])
    assert any(item["symbol"] == "SPY" and item["status"] == "degraded" for item in telemetry["degraded_inputs"])
    assert any("SPY: history served degraded" in message for message in collector.degraded)
    assert "upstream unavailable" not in payload
    assert "https://" not in payload
    assert "quotes" in registry.degraded_domains


def test_normal_collect_publishes_the_planned_telemetry(tmp_path: Path, monkeypatch) -> None:
    registry = _HistoryRegistry()
    collector = _collector(registry, tmp_path)
    monkeypatch.setattr(collector, "_collect_equities", lambda: EquitiesDataset(assets=[]))
    monkeypatch.setattr(collector, "_collect_crypto", lambda: CryptoDataset(assets=[]))
    monkeypatch.setattr(collector, "_collect_commodities", lambda: CommoditiesDataset(assets=[]))
    monkeypatch.setattr(collector, "_collect_sectors", lambda _equities: SectorsDataset(sectors=[], themes=[]))

    result = collector.collect()
    telemetry = result["provider_status"]["market"]["collection_telemetry"]

    assert telemetry["history_plan_count"] == telemetry["history_request_count"]
    assert telemetry["duplicate_request_keys"] == 0
    assert telemetry["request_keys"] == sorted(telemetry["request_keys"])
