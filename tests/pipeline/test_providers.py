"""Provider degradation chain tests (architecture §1.4; acceptance #3: yfinance outage → Stooq → degraded).

Also covers #62: the data-quality degrade factor has exactly one home, `pipeline/degrade.py`,
sourced from `config/sources.yaml` under `degrade.data_quality_degrade_factor`. Every consumer
— the four collectors, `risk.confidence.quality_factor`, and `ProviderRegistry` — resolves it
from there, so editing the config key moves all of them together.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from pipeline.collectors.calendar import CalendarCollector
from pipeline.collectors.macro import MacroCollector
from pipeline.collectors.market import MarketCollector
from pipeline.collectors.news import NewsCollector
from pipeline.degrade import (
    CONFIG_KEY,
    DEFAULT_DEGRADE_FACTOR,
    MIN_DATA_QUALITY,
    degrade_factor,
    degraded_quality,
)
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
from pipeline.risk.confidence import quality_factor
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_CONFIG_DIR = REPO_ROOT / "config"
PIPELINE_DIR = REPO_ROOT / "pipeline"

#: The factor as it was hardcoded at 41b11b9, before #62 extracted it. Tests that assert
#: "behaviour is unchanged at the default value" compare against this literal deliberately:
#: it is a frozen historical constant, not a reference to the current configuration.
LEGACY_FACTOR = 0.8


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


class _OkSeries(StooqProvider):
    """A single-provider success for the macro domain (get_series)."""
    name = "ok_series"

    def get_series(self, series_id: str) -> list[dict]:
        return [{"date": "2026-08-03", "value": 4.2}]

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=True)


class _FailSeries(StooqProvider):
    """A single-provider failure for the macro domain (get_series)."""
    name = "fail_series"

    def get_series(self, series_id: str) -> list[dict]:
        raise ProviderError(f"{series_id}: mock outage")

    def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, ok=False)


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


# ---------------------------------------------------------------------------
# #62 — one degrade factor, read from config, used everywhere
# ---------------------------------------------------------------------------


def _settings_with_factor(tmp_path: Path, value: float | None) -> Settings:
    """Copy the real config tree into tmp_path, optionally rewriting the degrade factor.

    Copying the real tree (rather than synthesising a minimal one) is deliberate: the
    acceptance criterion is that a value edited in a real-shaped `config/sources.yaml`
    reaches every consumer, so the test edits a real-shaped file.

    Passing ``value=None`` leaves the config untouched, which pins the default behaviour.
    """
    config_dir = tmp_path / "config"
    shutil.copytree(REAL_CONFIG_DIR, config_dir)
    if value is not None:
        path = config_dir / "sources.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["degrade"]["data_quality_degrade_factor"] = value
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Settings(
        _env_file=None,
        config_dir=config_dir,
        data_dir=tmp_path / "data",
        artifacts_dir=tmp_path / "artifacts",
    )


#: news and calendar degrade as a single unit — any number of failures is one failed source.
_BINARY_COLLECTORS = frozenset({"news", "calendar"})

#: Every collector whose published `data_quality` must track the configured factor.
COLLECTOR_NAMES = ("macro", "market", "news", "calendar")


def _effective_failures(collector: str, failed: int) -> int:
    """How many times the factor is actually applied for `failed` failed sources."""
    return min(failed, 1) if collector in _BINARY_COLLECTORS else failed


def _quality_at(settings: Settings, collector: str, failed: int) -> float:
    """Build `collector` against `settings`, degrade `failed` domains, read its quality.

    #65: the collectors' published quality is driven by `ProviderRegistry.degraded_domains`
    (its first reader), so a degraded run is reproduced by degrading that many domains on the
    registry rather than by poking private failure counters. The factor math is unchanged —
    `failed` degraded domains still cost `factor ** failed`.
    """
    registry = ProviderRegistry(settings)
    registry.degraded_domains.update({f"{collector}-{i}" for i in range(failed)})
    if collector == "macro":
        return MacroCollector(registry, settings)._quality()
    if collector == "market":
        return MarketCollector(registry, AssetUniverse(settings.load_universe()), settings)._quality()
    if collector == "news":
        return NewsCollector(registry, settings)._quality()
    if collector == "calendar":
        return CalendarCollector(registry, settings)._quality()
    raise AssertionError(f"unknown collector: {collector}")


def _max_failures(collector: str) -> int:
    """The largest failed-source count `collector` can represent."""
    if collector == "macro":
        return 2
    if collector in _BINARY_COLLECTORS:
        return 1
    return 4


# ---- The factor has exactly one home ----

_DEGRADE_LITERAL = re.compile(r"(?<![\w.])0\.8(?![\d])")

#: `pipeline/risk/scoring.py` holds indicator threshold tables where 0.8 is a credit-spread
#: level in percent (`ig_oas`) or a breadth ratio (`breadth_above_ma200`), not a degrade
#: factor. #62 names these as unrelated and leaves them.
_UNRELATED_TO_DEGRADE = frozenset({"pipeline/risk/scoring.py"})


def _degrade_literal_hits() -> list[str]:
    """Every bare 0.8 in the pipeline and config trees that a reader could take for a degrade factor."""
    searched = sorted(PIPELINE_DIR.rglob("*.py")) + sorted(REAL_CONFIG_DIR.rglob("*.yaml"))
    hits: list[str] = []
    for path in searched:
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative in _UNRELATED_TO_DEGRADE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _DEGRADE_LITERAL.search(line):
                hits.append(f"{relative}:{lineno}: {line.strip()}")
    return hits


def test_only_one_degrade_literal_in_pipeline() -> None:
    """AC: the degrade factor has exactly one home in code and exactly one in config.

    Scans both trees. Scoping this to `pipeline/` alone would let a phantom knob live in
    `config/` — which is exactly how `confidence.degrade_factor_per_fallback` survived in
    `risk_model.yaml`, one line beneath a block that *is* read.
    """
    hits = _degrade_literal_hits()

    assert len(hits) == 2, (
        "the degrade factor must have exactly one home in pipeline/ and one in config/; found:\n" + "\n".join(hits)
    )
    config_hit, code_hit = sorted(hits)  # "config/…" sorts before "pipeline/…"
    assert config_hit.startswith("config/sources.yaml:"), f"the config home must be sources.yaml, found {config_hit}"
    assert CONFIG_KEY in config_hit, f"the config literal must be {CONFIG_KEY}, found {config_hit}"
    assert code_hit.startswith("pipeline/degrade.py:"), f"the code home must be pipeline/degrade.py, found {code_hit}"
    assert "DEFAULT_DEGRADE_FACTOR" in code_hit, f"the code literal must define the default, found {code_hit}"


def test_no_second_degrade_key_in_risk_model_config() -> None:
    """`confidence.degrade_factor_per_fallback` is gone and does not come back.

    It was read by nothing while sitting directly beneath `confidence.weights`, which is
    read at `pipeline/risk/model.py:88` — so every signal a reader uses to judge it live
    was real. The `confidence:` block itself stays; `weights` is its live content.
    """
    raw = Settings(_env_file=None).load_risk_model()
    confidence_cfg = raw.get("confidence", {})

    assert "degrade_factor_per_fallback" not in confidence_cfg, (
        "the degrade factor must not have a second config key; sources.yaml owns it"
    )
    assert confidence_cfg.get("weights"), "confidence.weights is live (risk/model.py:88) and must survive"

    text = (REAL_CONFIG_DIR / "risk_model.yaml").read_text(encoding="utf-8")
    assert "degrade_factor_per_fallback" not in text, "the dead key must be deleted, not merely overridden"


def test_degrade_factor_is_single_sourced(tmp_path) -> None:
    """Every consumer reflects a patched config value — not just the one that reads config."""
    patched = 0.5
    settings = _settings_with_factor(tmp_path, patched)

    assert degrade_factor(settings) == patched
    assert ProviderRegistry(settings).degrade_factor == patched
    assert quality_factor(1, settings=settings) == patched

    for collector in COLLECTOR_NAMES:
        assert _quality_at(settings, collector, 1) == patched, f"{collector} ignored the configured factor"


def test_degrade_factor_honours_config_override(tmp_path) -> None:
    """A non-default factor in config/sources.yaml reaches quality_factor and all four collectors."""
    settings = _settings_with_factor(tmp_path, 0.5)

    assert quality_factor(1, settings=settings) == 0.5
    assert quality_factor(2, settings=settings) == 0.25

    assert _quality_at(settings, "macro", 1) == 0.5
    assert _quality_at(settings, "macro", 2) == 0.25
    assert _quality_at(settings, "market", 1) == 0.5
    assert _quality_at(settings, "market", 2) == 0.25
    assert _quality_at(settings, "news", 1) == 0.5
    assert _quality_at(settings, "calendar", 1) == 0.5

    # …and an undegraded run is still a clean 1.0 whatever the factor is.
    for collector in COLLECTOR_NAMES:
        assert _quality_at(settings, collector, 0) == 1.0


def test_degrade_factor_override_reaches_zero_arg_callers(tmp_path, monkeypatch) -> None:
    """A caller that passes no Settings still picks the value up from config, not from a default."""
    settings = _settings_with_factor(tmp_path, 0.25)
    monkeypatch.setenv("DATA_CONFIG_DIR", str(settings.config_dir))

    assert degrade_factor() == 0.25
    assert quality_factor(1) == 0.25


def test_degrade_factor_still_compounds(tmp_path) -> None:
    """Two failures yield factor ** 2, not factor. Compounding is deliberate precedent."""
    factor = 0.5
    settings = _settings_with_factor(tmp_path, factor)

    assert _quality_at(settings, "macro", 2) == factor**2
    assert _quality_at(settings, "market", 2) == factor**2
    assert quality_factor(2, settings=settings) == factor**2

    # Not the same as a single application — the bug this guards against.
    assert _quality_at(settings, "macro", 2) != factor
    assert _quality_at(settings, "market", 2) != factor
    assert quality_factor(2, settings=settings) != factor

    # …and it keeps compounding beyond two.
    assert _quality_at(settings, "market", 3) == pytest.approx(factor**3)


# ---- Behaviour is unchanged at the default value ----


@pytest.mark.parametrize("collector", COLLECTOR_NAMES)
def test_default_factor_preserves_published_quality(tmp_path, collector) -> None:
    """AC: at the default factor every published data_quality matches 41b11b9 exactly.

    This change touches no field other than `data_quality`, so pinning `data_quality`
    across the full degraded range is the byte-identity guarantee for the artifacts.
    """
    settings = _settings_with_factor(tmp_path, None)
    for failed in range(_max_failures(collector) + 1):
        applied = _effective_failures(collector, failed)
        # The pre-#62 expression, reproduced verbatim from each collector.
        expected = round(max(0.1, LEGACY_FACTOR**applied), 3)
        assert _quality_at(settings, collector, failed) == expected, (
            f"{collector} at {failed} failed source(s) drifted from the 41b11b9 value"
        )


def test_default_factor_preserves_quality_factor_output() -> None:
    """quality_factor keeps its 41b11b9 outputs when config carries the default."""
    for degraded_count in range(0, 11):
        expected = round(max(0.1, LEGACY_FACTOR**degraded_count), 4)
        assert quality_factor(degraded_count) == expected


def test_default_constant_matches_shipped_config() -> None:
    """The in-code fallback and the shipped config agree, so neither can drift unnoticed."""
    assert DEFAULT_DEGRADE_FACTOR == LEGACY_FACTOR
    assert degrade_factor(Settings(_env_file=None)) == DEFAULT_DEGRADE_FACTOR


# ---- The accessor itself ----


def test_degrade_factor_falls_back_when_key_absent(tmp_path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(REAL_CONFIG_DIR, config_dir)
    path = config_dir / "sources.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    del doc["degrade"]["data_quality_degrade_factor"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    settings = Settings(_env_file=None, config_dir=config_dir, artifacts_dir=tmp_path / "artifacts")
    assert degrade_factor(settings) == DEFAULT_DEGRADE_FACTOR


def test_degrade_factor_falls_back_when_section_absent(tmp_path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(REAL_CONFIG_DIR, config_dir)
    path = config_dir / "sources.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    del doc["degrade"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    settings = Settings(_env_file=None, config_dir=config_dir, artifacts_dir=tmp_path / "artifacts")
    assert degrade_factor(settings) == DEFAULT_DEGRADE_FACTOR


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, float("nan"), float("inf")])
def test_degrade_factor_rejects_values_outside_unit_interval(bad) -> None:
    """A factor outside (0, 1] would raise quality on degradation, or zero it. Refuse loudly."""
    with pytest.raises(ValueError, match="data_quality_degrade_factor"):
        degrade_factor(sources={"degrade": {"data_quality_degrade_factor": bad}})


@pytest.mark.parametrize("bad", ["zero point eight", None, [], {}])
def test_degrade_factor_rejects_non_numeric(bad: Any) -> None:
    with pytest.raises(ValueError, match="data_quality_degrade_factor"):
        degrade_factor(sources={"degrade": {"data_quality_degrade_factor": bad}})


def test_degrade_factor_accepts_a_preloaded_sources_mapping() -> None:
    """Callers holding sources.yaml already (ProviderRegistry) need not re-read it."""
    assert degrade_factor(sources={"degrade": {"data_quality_degrade_factor": 0.42}}) == 0.42


def test_degraded_quality_floors_at_minimum() -> None:
    """However many sources fail, published quality never claims less than the floor."""
    assert degraded_quality(50, factor=0.5) == MIN_DATA_QUALITY
    assert degraded_quality(0, factor=0.5) == 1.0


def test_degraded_quality_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="degraded_count"):
        degraded_quality(-1, factor=0.5)


@pytest.mark.parametrize("collector", COLLECTOR_NAMES)
def test_collector_quality_never_falls_below_floor(tmp_path, collector) -> None:
    settings = _settings_with_factor(tmp_path, 0.5)
    for failed in range(_max_failures(collector) + 1):
        assert _quality_at(settings, collector, failed) >= MIN_DATA_QUALITY


# ---------- #65: provenance names the answering provider ----------

def test_meta_names_the_answering_provider(tmp_path) -> None:
    """#65: a fallback chain reports the provider that succeeded, not the first tried."""
    reg = _registry(tmp_path)
    reg.register("quotes", _FailingYahoo())
    reg.register("quotes", _FailingYahoo())
    reg.register("quotes", _OkStooq())
    out = reg.call("quotes", "get_quote", "NVDA", args=("NVDA",))
    assert out["meta"]["provider"] == "stooq_ok", (
        f"meta must name the provider that answered, got {out['meta']['provider']}"
    )
    assert out["meta"]["used_fallback"] is True
    # The registry exposes the resolved provider for the domain.
    assert reg.resolved_provider("quotes")["provider"] == "stooq_ok"


def test_single_provider_domain_degrades_via_cache(tmp_path) -> None:
    """Ruling D: a single-provider domain degrades via the last-good cache path.

    crypto/macro/a_share/news each have one enabled provider but still degrade when it
    fails: `registry.call` replays the last-good cache and reports degraded/from_cache.
    """
    cache_dir = tmp_path / "cache"
    reg = _registry(cache_dir)
    reg.register("macro", _OkSeries())  # single provider
    reg.call("macro", "get_series", "fred_dgs10", args=("DGS10",))  # success → writes cache

    reg2 = _registry(cache_dir)
    reg2.register("macro", _FailSeries())  # sole provider now fails
    out = reg2.call("macro", "get_series", "fred_dgs10", args=("DGS10",))
    assert out["meta"]["degraded"] is True
    assert out["meta"]["from_cache"] is True
    assert out["meta"]["provider"] == "last-good"
    assert "macro" in reg2.degraded_domains
    assert reg2.resolved_provider("macro")["provider"] == "last-good"

    # The degraded domain lowers published quality (degraded_domains is the #65 reader).
    from pipeline.collectors.macro import MacroCollector

    collector = MacroCollector(reg2, Settings(_env_file=None))
    assert collector._quality() == degraded_quality(1, settings=Settings(_env_file=None))
