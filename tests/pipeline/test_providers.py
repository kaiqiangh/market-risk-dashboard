"""Provider degradation chain tests (architecture §1.4; acceptance #3: yfinance outage → Stooq → degraded)."""

from __future__ import annotations

import pytest

from pipeline.providers import ProviderRegistry
from pipeline.providers.base import (
    HistoryResult,
    ProviderError,
    ProviderHealth,
    QuoteResult,
    retry_with_backoff,
)
from pipeline.providers.stooq import StooqProvider
from pipeline.providers.yahoo import YahooProvider
from pipeline.settings import Settings


class _FailingYahoo(YahooProvider):
    name = "yfinance_fail"

    def get_quote(self, symbol: str) -> QuoteResult:
        raise ProviderError(f"{symbol}: yfinance outage (mock)")

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:
        raise ProviderError(f"{symbol}: yfinance outage (mock)")

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=False, error="mock down")


class _OkStooq(StooqProvider):
    name = "stooq_ok"

    def get_quote(self, symbol: str) -> QuoteResult:
        return QuoteResult(symbol=symbol, price=100.0, change_1d=1.2, provider=self.name, source="stooq", is_proxy=True)

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:
        rows = [
            {"date": "2026-07-01", "open": 90, "high": 95, "low": 89, "close": 92, "volume": 1000},
            {"date": "2026-08-03", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 1200},
        ]
        return HistoryResult(symbol=symbol, provider=self.name, rows=rows, period=period)

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True)


def _registry(cache_dir=None) -> ProviderRegistry:
    settings = Settings(_env_file=None)
    reg = ProviderRegistry(settings)
    if cache_dir is not None:
        reg.cache_dir = cache_dir
    return reg


def test_primary_ok_no_fallback(tmp_path) -> None:
    reg = _registry(tmp_path)
    reg.register("quotes", _OkStooq())
    out = reg.call("quotes", "get_quote", "NVDA", args=("NVDA",))
    assert out["meta"]["used_fallback"] is False
    assert out["meta"]["degraded"] is False
    assert out["result"].price == 100.0


def test_yahoo_fail_stooq_fallback_degraded(tmp_path) -> None:
    """Acceptance #3: yfinance outage → Stooq fallback → degraded."""
    reg = _registry(tmp_path)
    reg.register("quotes", _FailingYahoo())
    reg.register("quotes", _OkStooq())
    out = reg.call("quotes", "get_quote", "NVDA", args=("NVDA",))
    assert out["meta"]["used_fallback"] is True
    assert out["meta"]["degraded"] is True
    assert out["meta"]["provider"] == "stooq_ok"
    assert "quotes" in reg.degraded_domains
    # Fallback result carries the is_proxy marker
    assert out["result"].is_proxy is True


def test_all_fail_uses_last_good_cache(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    reg = _registry(cache_dir)
    reg.register("quotes", _OkStooq())
    reg.call("quotes", "get_quote", "NVDA", args=("NVDA",))  # success → writes cache

    reg2 = _registry(cache_dir)
    reg2.register("quotes", _FailingYahoo())
    out = reg2.call("quotes", "get_quote", "NVDA", args=("NVDA",))
    assert out["meta"]["from_cache"] is True
    assert out["meta"]["degraded"] is True
    assert out["result"].price == 100.0


def test_all_fail_no_cache_raises(tmp_path) -> None:
    reg = _registry(tmp_path)
    reg.register("quotes", _FailingYahoo())
    with pytest.raises(ProviderError):
        reg.call("quotes", "get_quote", "NVDA", args=("NVDA",))


def test_retry_with_backoff_succeeds_after_fail() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise ProviderError("flaky")
        return "ok"

    assert retry_with_backoff(flaky, max_retries=2, backoff_base=0.01, jitter=False) == "ok"
    assert calls["n"] == 2


def test_quality_factor_reduces_with_degrade() -> None:
    from pipeline.risk.confidence import quality_factor

    assert quality_factor(0) == 1.0
    assert quality_factor(1) == 0.8  # ×0.8 per degrade
    assert quality_factor(2) == 0.64
    assert quality_factor(10) >= 0.1  # clamped


def test_confidence_drops_when_data_quality_drops() -> None:
    from pipeline.risk.confidence import compute_confidence

    high = compute_confidence(1.0, 0.9, 1.0)
    low = compute_confidence(0.64, 0.9, 1.0)  # dq=0.8 after one degrade
    assert low < high
