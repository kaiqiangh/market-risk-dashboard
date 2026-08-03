"""News dataset contract (architecture §3.5 NewsItem).

Copyright boundary: store only title+source+link+self-written one-sentence summary, not full text
(PRD §24, architecture §8.13). id = sha1(title+source+published) dedupe key (computed by T03 NewsCollector).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

NewsSentiment = Literal["positive", "negative", "neutral"]
NewsSourceLang = Literal["en", "zh"]


class NewsItem(ContractModel):
    id: str = Field(min_length=1, description="sha1(title+source+published) dedupe key")
    title: str = Field(min_length=1, description="English headline (canonical bilingual, ADR-0003)")
    title_zh: str | None = None
    lang: NewsSourceLang = Field(default="en", description="source feed language; translation routing only, never a display string (ADR-0003)")
    source: str = Field(min_length=1)
    url: str = Field(min_length=1)
    published_at: UTCDateTime
    categories: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0.0, le=100.0)
    sentiment: NewsSentiment | None = None
    summary: str = Field(default="", description="English one-sentence summary (canonical bilingual, ADR-0003)")
    summary_zh: str | None = Field(default=None, description="Chinese translation of the summary (canonical bilingual, ADR-0003)")
    impact_window: str | None = None


class NewsDataset(ContractModel):
    """news.json payload."""

    items: list[NewsItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    updated_at: UTCDateTime | None = None


class NewsEnvelope(BaseEnvelope):
    payload: NewsDataset


class NewsTranslation(ContractModel):
    """Symmetric full-pair translation of a news item (AI automation produces news.zh-translations.json, ADR-0003).

    Carries both English (title/summary) and Chinese (title_zh/summary_zh) for the same id; merge copies
    both sides without overwriting the canonical English (title/summary) of the item.
    """

    id: str = Field(min_length=1, description="corresponding NewsItem.id")
    title: str | None = Field(default=None, description="English title (required for zh-source items)")
    summary: str | None = Field(default=None, description="English summary (required for zh-source items)")
    title_zh: str = Field(min_length=1)
    summary_zh: str | None = None


class NewsTranslationsDataset(ContractModel):
    """news.zh-translations.json (architecture §1.5: merged into news.json on the next pipeline run)."""

    items: list[NewsTranslation] = Field(default_factory=list)
    updated_at: UTCDateTime | None = None
