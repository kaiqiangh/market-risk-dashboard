"""Pipeline runtime configuration: pydantic-settings reads .env + config/*.yaml.

Architecture §3.5/§1.3: API keys live only in the local .env (gitignored); keys must never
appear in the frontend/CI. This file is the T01 skeleton: defines the Settings structure +
YAML loading utilities; used by Collectors since T03.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root directory (pipeline/settings.py → parent)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Global pipeline configuration.

    Environment variable prefix DATA_ (e.g. DATA_FRED_API_KEY in .env.example).
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_prefix="DATA_",
        case_sensitive=False,
        extra="ignore",
    )

    fred_api_key: str | None = Field(default=None, description="FRED API key (local .env)")
    coingecko_api_key: str | None = Field(default=None, description="CoinGecko Demo key")
    fmp_api_key: str | None = Field(default=None, description="FMP free-tier key")

    # Directories (relative to project root)
    project_root: Path = PROJECT_ROOT
    config_dir: Path = PROJECT_ROOT / "config"
    data_dir: Path = PROJECT_ROOT / "public" / "data"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"

    # ---- YAML config loading ----

    def _load_yaml(self, name: str) -> dict[str, Any]:
        """Read config/{name}.yaml and return a dict; raises ConfigError when the file is missing or invalid."""
        path = self.config_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"config file missing: {path}")
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"config file must be a YAML mapping: {path}")
        return data

    def load_universe(self) -> dict[str, Any]:
        """Asset universe (config/universe.yaml)."""
        return self._load_yaml("universe")

    def load_risk_model(self) -> dict[str, Any]:
        """Risk model weights/indicators/thresholds (config/risk_model.yaml)."""
        return self._load_yaml("risk_model")

    def load_sources(self) -> dict[str, Any]:
        """Provider registry/degradation/expected frequency (config/sources.yaml)."""
        return self._load_yaml("sources")

    def load_news_sources(self) -> dict[str, Any]:
        """News sources and importance rules (config/news_sources.yaml)."""
        return self._load_yaml("news_sources")

    # ---- Validated config (#102, pipeline/config/models.py) ----
    #
    # The raw loaders above remain for the loose readers (freshness expectations,
    # importance rules). The validated loaders below are what the provider factory, the
    # collectors and the universe use — a typo now raises ConfigError before any provider
    # is constructed, instead of silently disabling a theme.

    def load_sources_config(self) -> "SourcesConfig":
        """Validated sources.yaml (providers/degrade/operations) — raises ConfigError on drift."""
        from pipeline.config.models import SourcesConfig, load_config

        return load_config(self.config_dir / "sources.yaml", SourcesConfig)

    def load_universe_config(self) -> "UniverseConfig":
        """Validated universe.yaml — no theme tags (#102)."""
        from pipeline.config.models import UniverseConfig, load_config

        return load_config(self.config_dir / "universe.yaml", UniverseConfig)

    def load_themes_config(self) -> "ThemesConfig":
        """Validated themes.yaml; every constituent must resolve in universe.yaml."""
        from pipeline.config.models import ConfigError, ThemesConfig, load_config

        themes = load_config(self.config_dir / "themes.yaml", ThemesConfig)
        universe = self.load_universe_config()
        known = {
            a.symbol
            for pool in (universe.us_equities, universe.a_share_memory)
            for a in pool
        }
        for section in ("sectors", "themes"):
            for key, theme in getattr(themes, section).items():
                for constituent in theme.constituents:
                    if constituent.symbol not in known:
                        raise ConfigError(
                            f"themes.yaml:{section}.{key}: constituent "
                            f"{constituent.symbol!r} does not resolve in universe.yaml"
                        )
        return themes

    def load_news_sources_config(self) -> "NewsSourcesConfig":
        """Validated news_sources.yaml — the assets/categories blocks are gone (#102)."""
        from pipeline.config.models import NewsSourcesConfig, load_config

        return load_config(self.config_dir / "news_sources.yaml", NewsSourcesConfig)


# Module-level singleton (reused by run.py and Collectors since T03)
settings = Settings()
