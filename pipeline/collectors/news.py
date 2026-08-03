"""新闻采集器（架构 §3.7 NewsCollector + §1.5 中译合并）。

- id = sha1(title+source+published) 去重键
- importance 规则评分 0-100（来源权重 + 关键词 + 资产命中 + 时效）
- 只存标题/来源/链接/自写摘要，不存全文（版权边界）
- merge_translations：把 news.zh-translations.json 合并进 news.json（单一事实源）
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import NewsDataset, NewsEnvelope, NewsItem, NewsTranslationsDataset
from pipeline.settings import Settings

_HTML_RE = re.compile(r"<[^>]+>")
_ASSET_ALIASES = {
    "NVDA": ["nvidia", "英伟达"],
    "AVGO": ["broadcom", "博通"],
    "MU": ["micron", "美光"],
    "AMD": ["amd", "超威"],
    "TSLA": ["tesla", "特斯拉"],
    "BTC": ["bitcoin", "比特币", "btc"],
    "ETH": ["ethereum", "以太坊", "eth"],
}


class NewsCollector:
    def __init__(self, registry: ProviderRegistry, settings: Settings | None = None) -> None:
        self.registry = registry
        self.settings = settings or Settings()
        rules = self.settings.load_news_sources().get("importance", {})
        self.source_weight = float(rules.get("source_weight", 30))
        self.keyword_weight = float(rules.get("keyword_weight", 30))
        self.asset_hit_weight = float(rules.get("asset_hit_weight", 20))
        self.recency_weight = float(rules.get("recency_weight", 20))
        self.high_keywords = [k.lower() for k in rules.get("keywords", {}).get("high", [])]
        self.degraded: list[str] = []

    def _dedupe_id(self, title: str, source: str, published: str) -> str:
        return hashlib.sha1(f"{title}|{source}|{published}".encode("utf-8")).hexdigest()

    def _score_importance(self, item: dict[str, Any], now: datetime) -> float:
        title = item["title"].lower()
        # 来源权重（按 news_sources.yaml 的 source weight，缺省取 1）
        source_cfg = self.settings.load_news_sources().get("sources", [])
        weight = next((float(s.get("weight", 1)) for s in source_cfg if s.get("id") == item.get("source_id")), 1.0)
        source_score = self.source_weight * min(weight / 4.0, 1.0)

        keyword_hits = sum(1 for kw in self.high_keywords if kw in title)
        keyword_score = self.keyword_weight * min(keyword_hits / 3.0, 1.0)

        asset_hits = self._map_assets(title)
        asset_score = self.asset_hit_weight * min(len(asset_hits) / 2.0, 1.0)

        try:
            published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        except ValueError:
            published = now
        age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
        recency_score = self.recency_weight * max(0.0, 1.0 - age_hours / 48.0)

        return round(min(100.0, source_score + keyword_score + asset_score + recency_score), 2)

    def _map_assets(self, title: str) -> list[str]:
        low = title.lower()
        hits: list[str] = []
        for symbol, aliases in _ASSET_ALIASES.items():
            if any(a in low for a in aliases):
                hits.append(symbol)
        return hits

    def _category(self, item: dict[str, Any]) -> list[str]:
        low = item["title"].lower()
        if item.get("category_hint"):
            return [str(item["category_hint"])]
        if any(k in low for k in ("fed", "利率", "cpi", "通胀", "inflation", "yield")):
            return ["macro", "monetary_policy"]
        if any(k in low for k in ("memory", "dram", "nand", "存储", "减产")):
            return ["memory"]
        if any(k in low for k in ("bitcoin", "crypto", "比特币")):
            return ["crypto"]
        if any(k in low for k in ("earnings", "财报", "quarter")):
            return ["earnings"]
        return ["other"]

    def collect(self) -> tuple[NewsEnvelope, dict[str, Any]]:
        try:
            out = self.registry.call("news", "fetch_news", "rss_all")
            raw_items: list[dict[str, Any]] = out["result"]
            provider = out["meta"].get("provider", "rss_news")
        except ProviderError as exc:
            self.degraded.append(str(exc))
            raw_items = []
            provider = "rss_news"

        now = datetime.now(timezone.utc)
        items: list[NewsItem] = []
        seen: set[str] = set()
        for raw in raw_items:
            title = _clean(raw.get("title", ""))
            source = raw.get("source", "unknown")
            published = raw.get("published_at", _now_utc())
            dedupe_id = self._dedupe_id(title, source, published)
            if dedupe_id in seen:
                continue
            seen.add(dedupe_id)
            items.append(
                NewsItem(
                    id=dedupe_id,
                    title=title,
                    title_zh=None,
                    source=source,
                    url=raw.get("url", ""),
                    published_at=published,
                    categories=self._category(raw),
                    assets=self._map_assets(title),
                    importance=self._score_importance(raw, now),
                    sentiment=None,
                    summary=raw.get("summary", "")[:160],
                    impact_window=None,
                )
            )

        items.sort(key=lambda n: n.importance, reverse=True)
        items = items[:50]

        quality = 0.8 if self.degraded else 1.0  # 按失败源降级 ×0.8
        envelope = NewsEnvelope(
            generated_at=_now_utc(), schema_version="1.0.0",
            source=[provider], source_updated_at=_now_utc(),
            freshness_status="degraded" if self.degraded else "fresh",
            data_quality=round(quality, 3),
            payload=NewsDataset(items=items, total=len(items), updated_at=_now_utc()),
        )
        return envelope, {"degraded": self.degraded, "provider": provider}

    # ---- 中译合并（架构 §1.5 步骤 4）----

    def merge_translations(self, news: NewsEnvelope, translations: NewsTranslationsDataset | None) -> NewsEnvelope:
        """把 AI 产出的中译合并进 news.json（title_zh/summary_zh）。"""
        if translations is None or not translations.items:
            return news
        by_id = {t.id: t for t in translations.items}
        updated_items = []
        for item in news.payload.items:
            trans = by_id.get(item.id)
            if trans is not None:
                updated_items.append(
                    item.model_copy(update={"title_zh": trans.title_zh, "summary": trans.summary_zh or item.summary})
                )
            else:
                updated_items.append(item)
        return news.model_copy(update={"payload": news.payload.model_copy(update={"items": updated_items})})


def _clean(text: str) -> str:
    text = _HTML_RE.sub(" ", text or "")
    return " ".join(text.split())


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
