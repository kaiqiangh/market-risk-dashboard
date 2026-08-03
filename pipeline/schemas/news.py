"""新闻数据集契约（架构 §3.5 NewsItem）。

版权边界：仅存标题+来源+链接+自写一句话摘要，不存全文（PRD §24，架构 §8.13）。
id = sha1(title+source+published) 去重键（T03 NewsCollector 计算）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

NewsSentiment = Literal["positive", "negative", "neutral"]


class NewsItem(ContractModel):
    id: str = Field(min_length=1, description="sha1(title+source+published) 去重键")
    title: str = Field(min_length=1)
    title_zh: str | None = None
    source: str = Field(min_length=1)
    url: str = Field(min_length=1)
    published_at: UTCDateTime
    categories: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    importance: float = Field(ge=0.0, le=100.0)
    sentiment: NewsSentiment | None = None
    summary: str = Field(default="", description="自写一句话摘要（不存全文）")
    impact_window: str | None = None


class NewsDataset(ContractModel):
    """news.json payload。"""

    items: list[NewsItem] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    updated_at: UTCDateTime | None = None


class NewsEnvelope(BaseEnvelope):
    payload: NewsDataset


class NewsTranslation(ContractModel):
    """英文新闻中译条目（AI 自动化产出 news.zh-translations.json）。"""

    id: str = Field(min_length=1, description="对应 NewsItem.id")
    title_zh: str = Field(min_length=1)
    summary_zh: str | None = None


class NewsTranslationsDataset(ContractModel):
    """news.zh-translations.json（架构 §1.5：管道下次运行合并进 news.json）。"""

    items: list[NewsTranslation] = Field(default_factory=list)
    updated_at: UTCDateTime | None = None
