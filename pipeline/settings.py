"""管道运行时配置：pydantic-settings 读 .env + config/*.yaml。

架构 §3.5/§1.3：API key 只在本机 .env（已 gitignore）；前端/CI 不得出现 key。
本文件为 T01 骨架：定义 Settings 结构 + YAML 加载工具；T03 起被 Collectors 使用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（pipeline/settings.py → 上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局管道配置。

    环境变量前缀 DATA_（对应 .env.example 中的 DATA_FRED_API_KEY 等）。
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_prefix="DATA_",
        case_sensitive=False,
        extra="ignore",
    )

    fred_api_key: str | None = Field(default=None, description="FRED API key（本机 .env）")
    coingecko_api_key: str | None = Field(default=None, description="CoinGecko Demo key")
    fmp_api_key: str | None = Field(default=None, description="FMP 免费层 key")

    # 目录（相对项目根）
    project_root: Path = PROJECT_ROOT
    config_dir: Path = PROJECT_ROOT / "config"
    data_dir: Path = PROJECT_ROOT / "public" / "data"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"

    # ---- YAML 配置加载 ----

    def _load_yaml(self, name: str) -> dict[str, Any]:
        """读取 config/{name}.yaml 并返回 dict；文件缺失或非法时抛 ConfigError。"""
        path = self.config_dir / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"配置文件缺失: {path}")
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"配置文件必须是 YAML 映射: {path}")
        return data

    def load_universe(self) -> dict[str, Any]:
        """资产池（config/universe.yaml）。"""
        return self._load_yaml("universe")

    def load_risk_model(self) -> dict[str, Any]:
        """风险模型权重/指标/阈值（config/risk_model.yaml）。"""
        return self._load_yaml("risk_model")

    def load_sources(self) -> dict[str, Any]:
        """Provider 注册表/降级/期望频率（config/sources.yaml）。"""
        return self._load_yaml("sources")

    def load_news_sources(self) -> dict[str, Any]:
        """新闻源与重要性规则（config/news_sources.yaml）。"""
        return self._load_yaml("news_sources")


# 模块级单例（T03 起被 run.py 与 Collectors 复用）
settings = Settings()
