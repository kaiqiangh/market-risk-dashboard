"""News collector (architecture §3.7 NewsCollector + §1.5 Chinese translation merge).

- id = sha1(title+source+published) dedupe key
- importance rule scoring 0-100 (source weight + keyword + asset hit + recency)
- stores only title/source/link/self-written summary, not full text (copyright boundary)
- merge_translations: merges news.zh-translations.json into news.json (single source of truth)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from pipeline.degrade import degraded_quality
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import NewsDataset, NewsItem, NewsTranslationsDataset
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse
from pipeline.utils import now_utc

_HTML_RE = re.compile(r"<[^>]+>")


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
        # #102 (D-8): asset-hit aliases derive from the universe (symbol/name/name_zh),
        # replacing the hardcoded table. Ops knobs (M-5) come from sources.yaml:operations.
        self._asset_aliases = AssetUniverse.load(self.settings).news_aliases()
        operations = self.settings.load_sources_config().operations
        self.recency_half_life_hours = float(operations.recency_half_life_hours)
        self.news_max_items = int(operations.news_max_items)
        self.news_summary_max_chars = int(operations.news_summary_max_chars)
        self.degraded: list[str] = []

    def _dedupe_id(self, title: str, source: str, published: str) -> str:
        return hashlib.sha1(f"{title}|{source}|{published}".encode("utf-8")).hexdigest()

    def _score_importance(self, item: dict[str, Any], now: datetime) -> float:
        title = item["title"].lower()
        # Source weight (per news_sources.yaml source weight, default 1)
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
        recency_score = self.recency_weight * max(0.0, 1.0 - age_hours / self.recency_half_life_hours)

        return round(min(100.0, source_score + keyword_score + asset_score + recency_score), 2)

    def _map_assets(self, title: str) -> list[str]:
        low = title.lower()
        hits: list[str] = []
        for symbol, aliases in self._asset_aliases.items():
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

    # ---- Summary ----

    def _quality(self) -> float:
        """Data quality degrades by the configured factor per degraded domain (#65).

        News degrades as a unit: the registry's `degraded_domains` is the reader — a news
        fallback or cache replay lowers published quality.
        """
        return degraded_quality(len(self.registry.degraded_domains), settings=self.settings)

    def collect(self) -> tuple[NewsDataset, dict[str, Any]]:
        outcome: dict[str, Any] = {"provider": "rss_news", "used_fallback": False, "from_cache": False}
        try:
            out = self.registry.call("news", "fetch_news", "rss_all")
            raw_items: list[dict[str, Any]] = out["result"]
            outcome = {
                "provider": str(out["meta"].get("provider", "rss_news")),
                "used_fallback": bool(out["meta"].get("used_fallback", False)),
                "from_cache": bool(out["meta"].get("from_cache", False)),
            }
            provider = outcome["provider"]
        except ProviderError as exc:
            self.degraded.append(str(exc))
            raw_items = []
            provider = "rss_news"

        # Source reachability (Fix R3): recorded by RssNewsProvider, written to sources status for the system status page
        source_status: dict[str, Any] = {}
        for p in self.registry.providers_for("news"):
            if hasattr(p, "source_status"):
                source_status.update(p.source_status)

        source_failures = [source_id for source_id, status in source_status.items() if not status.get("ok", False)]
        if source_failures:
            self.degraded.append("RSS sources degraded: " + ", ".join(sorted(source_failures)))

        now = datetime.now(timezone.utc)
        items: list[NewsItem] = []
        seen: set[str] = set()
        for raw in raw_items:
            title = _clean(raw.get("title", ""))
            source = raw.get("source", "unknown")
            published = raw.get("published_at")
            if not published:
                self.degraded.append(f"news item missing published_at: {title[:80]}")
                continue
            dedupe_id = self._dedupe_id(title, source, published)
            if dedupe_id in seen:
                continue
            seen.add(dedupe_id)
            items.append(
                NewsItem(
                    id=dedupe_id,
                    title=title,
                    title_zh=None,
                    lang="zh" if raw.get("lang", "en") == "zh" else "en",
                    source=source,
                    url=raw.get("url", ""),
                    published_at=published,
                    categories=self._category(raw),
                    assets=self._map_assets(title),
                    importance=self._score_importance(raw, now),
                    sentiment=None,
                    summary=raw.get("summary", "")[: self.news_summary_max_chars],
                    impact_window=None,
                )
            )

        items.sort(key=lambda n: n.importance, reverse=True)
        items = items[: self.news_max_items]

        quality = self._quality()
        # #64: return payload + provider outcome; the caller assembles the envelope and
        # finalizes freshness through the single assembly path.
        payload = NewsDataset(items=items, total=len(items), updated_at=now_utc())
        return payload, {
            "degraded": self.degraded,
            "provider": provider,
            "source_status": source_status,
            "provider_outcome": outcome,
            "data_quality": round(quality, 3),
        }

    # ---- Chinese translation merge (architecture §1.5 step 4; ADR-0003) ----

    def merge_translations(self, news: NewsDataset, translations: NewsTranslationsDataset | None) -> NewsDataset:
        """Merge AI-produced symmetric full-pair translations into the news payload.

        Canonical bilingual model (ADR-0003): `summary`/`title` stay English, `summary_zh`/`title_zh`
        carry Chinese. A translation record carries both sides; this copies whatever it provides and
        never replaces the canonical English with Chinese (the pre-ADR-0003 overwrite bug).
        """
        if translations is None or not translations.items:
            return news
        by_id = {t.id: t for t in translations.items}
        updated_items = []
        for item in news.items:
            trans = by_id.get(item.id)
            if trans is None:
                updated_items.append(item)
                continue
            update: dict[str, Any] = {}
            # Chinese side (en-source items): overlay the translation.
            for field, value in (("title_zh", trans.title_zh), ("summary_zh", trans.summary_zh)):
                if value:
                    update[field] = value
            # English side: written only for zh-source items, whose canonical English is missing
            # (their raw feed text is Chinese). en-source items already hold canonical English —
            # the record's English side is their own text verbatim and is never rewritten.
            if item.lang == "zh":
                for field, value in (("title", trans.title), ("summary", trans.summary)):
                    if value:
                        update[field] = value
            updated_items.append(item.model_copy(update=update) if update else item)
        return news.model_copy(update={"items": updated_items})


def _clean(text: str) -> str:
    text = _HTML_RE.sub(" ", text or "")
    return " ".join(text.split())
