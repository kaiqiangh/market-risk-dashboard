"""News dataset contract (architecture §3.5 NewsItem).

Copyright boundary: store only title+source+link+self-written one-sentence summary, not full text
(PRD §24, architecture §8.13). id = sha1(title+source+published) dedupe key (computed by T03 NewsCollector).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

NewsSentiment = Literal["positive", "negative", "neutral"]


class NewsItem(ContractModel):
    id: str = Field(min_length=1, description="sha1(title+source+published) dedupe key")
    title: str = Field(min_length=1)
    title_zh: str | None = None
    source: str = Field(min_length=1)
    url: str = Field(min_length=1)
    published_at: UTCDateTime
    categories: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0.0, le=100.0)
    sentiment: NewsSentiment | None = None
    summary: str = Field(default="", description="self-written one-sentence summary (no full text)")
    impact_window: str | None = None


class NewsDataset(ContractModel):
    """news.json payload."""

    items: list[NewsItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    updated_at: UTCDateTime | None = None


class NewsEnvelope(BaseEnvelope):
    payload: NewsDataset


class NewsTranslation(ContractModel):
    """Chinese translation of an English news item (AI automation produces news.zh-translations.json)."""

    id: str = Field(min_length=1, description="corresponding NewsItem.id")
    title_zh: str = Field(min_length=1)
    summary_zh: str | None = None


class NewsTranslationsDataset(ContractModel):
    """news.zh-translations.json (architecture §1.5: merged into news.json on the next pipeline run)."""

    items: list[NewsTranslation] = Field(default_factory=list)
    updated_at: UTCDateTime | None = None
