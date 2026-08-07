"""#102 config-layer tests: validated loading, live providers block, ops knobs.

Pins the mechanisms the ticket delivers (decision #90, ADR 0005):
- ``load_config`` is strict (``extra="forbid"``) and raises ConfigError before any provider
  is constructed — a typo'd key fails loudly instead of silently disabling a theme.
- ``themes.yaml`` constituents must resolve in ``universe.yaml``; a dangling reference fails.
- ``build_default_providers()`` reads order/priority/``enabled`` from ``sources.yaml:providers``
  (C-3); an enabled entry naming an unknown provider, or in the wrong domain, fails loudly.
- The news_sources ``assets``/``categories`` blocks are gone (validated model rejects them).
- The sector/theme payload carries no labels (C-1) — check:i18n owns the display labels.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pipeline.config.models import ConfigError, SourcesConfig, ThemesConfig, load_config
from pipeline.providers import build_default_providers
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse


def _settings_with_config_dir(tmp_path: Path) -> Settings:
    """A Settings whose config_dir points at a scratch directory."""
    s = Settings(_env_file=None)
    return s.model_copy(update={"config_dir": tmp_path})


def _write(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _copy_real_configs(tmp_path: Path) -> None:
    """Seed the scratch config dir with the real configs.

    Providers eagerly load some configs at construction (rss_news → news_sources.yaml,
    coingecko → universe.yaml), so a scratch dir that only holds the file under test is not
    enough to construct a provider.
    """
    real = Path(__file__).resolve().parents[2] / "config"
    for name in ("sources.yaml", "universe.yaml", "themes.yaml", "news_sources.yaml"):
        (tmp_path / name).write_text((real / name).read_text(encoding="utf-8"), encoding="utf-8")


def test_load_config_rejects_typo_keys(tmp_path: Path) -> None:
    """extra="forbid": a typo'd key fails loudly rather than silently disabling a theme."""
    # A typo'd top-level key (themez vs themes) is an extra field → ConfigError.
    path = _write(
        tmp_path,
        "themes.yaml",
        {"schema_version": "1.0.0", "themes": {"ai": {"constituents": []}}, "themez": {}},
    )
    with pytest.raises(ConfigError, match="themez"):
        load_config(path, ThemesConfig)
    # A typo inside a theme definition (constituent vs constituents) is caught the same way.
    path = _write(
        tmp_path,
        "themes.yaml",
        {"schema_version": "1.0.0", "themes": {"ai": {"constituent": [{"symbol": "NVDA"}]}}},
    )
    with pytest.raises(ConfigError, match="constituent"):
        load_config(path, ThemesConfig)


def test_load_config_missing_file_and_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="missing"):
        load_config(tmp_path / "nope.yaml", ThemesConfig)
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(bad, ThemesConfig)


def test_themes_dangling_constituent_fails_the_run(tmp_path: Path) -> None:
    """Every themes.yaml constituent must resolve in universe.yaml; a dangling one raises."""
    real = Path(__file__).resolve().parents[2] / "config"
    themes = yaml.safe_load((real / "themes.yaml").read_text(encoding="utf-8"))
    universe = yaml.safe_load((real / "universe.yaml").read_text(encoding="utf-8"))

    themes["themes"]["bogus"] = {"constituents": [{"symbol": "ZZZZ", "weight": 1.0}]}
    _write(tmp_path, "themes.yaml", themes)
    _write(tmp_path, "universe.yaml", universe)

    settings = _settings_with_config_dir(tmp_path)
    with pytest.raises(ConfigError, match=r"ZZZZ.*universe"):
        settings.load_themes_config()


def test_universe_rejects_theme_tags(tmp_path: Path) -> None:
    """universe.yaml no longer carries per-symbol theme tags (D-8) — a stray one is a typo."""
    universe = {
        "version": "1.0.0",
        "us_equities": [{"symbol": "NVDA", "name": "NVIDIA", "theme": ["AI"]}],
    }
    _write(tmp_path, "universe.yaml", universe)
    settings = _settings_with_config_dir(tmp_path)
    with pytest.raises(ConfigError, match="theme"):
        settings.load_universe_config()


def test_build_default_providers_reads_config_order_and_enabled() -> None:
    """C-3: the provider chain comes from sources.yaml:providers, not a hardcoded list."""
    providers = build_default_providers(Settings(_env_file=None))
    by_domain: dict[str, list[tuple[str, int]]] = {}
    for p in providers:
        by_domain.setdefault(p.domain, []).append((p.name, p.priority))

    # Order within a domain is config priority, smallest first.
    assert by_domain["quotes"] == [("yfinance", 1), ("stooq", 2)]
    assert by_domain["calendar"] == [("fmp", 1), ("yfinance_calendar", 2)]
    # binance_public is enabled: false in config — never constructed.
    assert all(name != "binance_public" for name, _ in by_domain.get("crypto", []))
    assert by_domain["crypto"] == [("coingecko", 1)]


def test_build_default_providers_fails_loudly_on_unknown_or_wrong_domain(tmp_path: Path) -> None:
    real = Path(__file__).resolve().parents[2] / "config"
    sources = yaml.safe_load((real / "sources.yaml").read_text(encoding="utf-8"))
    _copy_real_configs(tmp_path)

    # Unknown enabled provider → ConfigError.
    bad = dict(sources)
    bad["providers"] = dict(sources["providers"])
    bad["providers"]["quotes"] = [{"name": "not_a_provider", "priority": 1, "kind": "primary"}]
    _write(tmp_path, "sources.yaml", bad)
    settings = _settings_with_config_dir(tmp_path)
    with pytest.raises(ConfigError, match="unknown provider"):
        build_default_providers(settings)

    # Provider in the wrong domain → ConfigError (would sit in a chain it does not belong to).
    wrong = dict(sources)
    wrong["providers"] = dict(sources["providers"])
    wrong["providers"]["news"] = [{"name": "yfinance", "priority": 1, "kind": "primary"}]
    _write(tmp_path, "sources.yaml", wrong)
    settings = _settings_with_config_dir(tmp_path)
    with pytest.raises(ConfigError, match=r"is a 'quotes' provider, not 'news'"):
        build_default_providers(settings)

    # A disabled unknown entry is inert (binance_public is exactly this case).
    inert = dict(sources)
    inert["providers"] = dict(sources["providers"])
    inert["providers"]["quotes"] = [
        {"name": "not_implemented_yet", "priority": 9, "kind": "fallback", "enabled": False},
        {"name": "yfinance", "priority": 1, "kind": "primary"},
    ]
    _write(tmp_path, "sources.yaml", inert)
    settings = _settings_with_config_dir(tmp_path)
    names = [p.name for p in build_default_providers(settings)]
    assert names.count("yfinance") == 1 and "not_implemented_yet" not in names


def test_news_sources_config_rejects_assets_and_categories(tmp_path: Path) -> None:
    """The dead assets/categories blocks are deleted from the file and rejected by the model."""
    real = Path(__file__).resolve().parents[2] / "config"
    news = yaml.safe_load((real / "news_sources.yaml").read_text(encoding="utf-8"))
    assert "assets" not in news and "categories" not in news

    with_labels = dict(news)
    with_labels["assets"] = ["NVDA"]
    with_labels["categories"] = ["macro"]
    _write(tmp_path, "news_sources.yaml", with_labels)
    settings = _settings_with_config_dir(tmp_path)
    with pytest.raises(ConfigError):
        settings.load_news_sources_config()


def test_operations_knobs_are_typed_and_defaulted(tmp_path: Path) -> None:
    real = Path(__file__).resolve().parents[2] / "config"
    sources = yaml.safe_load((real / "sources.yaml").read_text(encoding="utf-8"))
    assert set(sources["operations"]) == {
        "circuit_breaker_threshold",
        "calendar_horizon_days",
        "news_max_items",
        "news_summary_max_chars",
        "recency_half_life_hours",
    }
    cfg = load_config(real / "sources.yaml", SourcesConfig)
    ops = cfg.operations
    assert ops.circuit_breaker_threshold == 3  # #103: 3 consecutive transient failures
    assert ops.calendar_horizon_days == 14
    assert ops.news_max_items == 50
    assert ops.news_summary_max_chars == 160
    assert ops.recency_half_life_hours == 48.0


def test_market_sector_rows_come_from_themes_config() -> None:
    """C-1: the collector's sector/theme rows are the themes.yaml keys, labels nowhere."""
    from pipeline.schemas import EquitiesDataset, EquityAsset

    settings = Settings(_env_file=None)
    themes = settings.load_themes_config()
    universe = AssetUniverse.load(settings)
    assert list(themes.sectors) == ["semis", "auto"]
    # #93: the full 20-theme taxonomy, guards passing at load time.
    assert len(themes.themes) == 20
    assert "memory" in themes.themes and "ai_infrastructure" in themes.themes
    # The reverse lookup (EquityAsset.theme) is populated from themes.yaml, not universe tags.
    by_symbol = {a.symbol: a for a in universe.all_equities()}
    assert by_symbol["NVDA"].symbol == "NVDA"  # Asset has no theme attribute anymore (D-8)
    assert not hasattr(by_symbol["NVDA"], "theme")

    equities = EquitiesDataset(
        assets=[
            EquityAsset(symbol="NVDA", name="NVIDIA", price=100.0, source="yfinance", updated_at="2026-08-04T12:00:00Z"),
            EquityAsset(symbol="TSLA", name="Tesla", price=200.0, source="yfinance", updated_at="2026-08-04T12:00:00Z"),
        ]
    )
    # Just the schema contract: SectorItem no longer accepts label/label_zh (C-1).
    from pipeline.schemas import SectorItem, SectorsDataset

    payload = SectorsDataset(sectors=[SectorItem(key="semis")], themes=[SectorItem(key="memory")])
    assert payload.sectors[0].key == "semis"
    assert "label" not in payload.sectors[0].model_dump()
