"""News RSS Provider (architecture §1.3/§8.13 copyright boundary + Fix round R3 Chinese sources).

Only title/source/link/publish time/self-written summary are kept, not full text. The source list
comes from config/news_sources.yaml. Importance scoring (0-100) is done in NewsCollector
(source weight + keyword + asset hit + recency).

Degradation semantics (Fix rounds): a single failed/unreachable source → recorded in source_status
(degraded) → continue with other sources; ProviderError is raised only when ALL sources fail.
source_status is written by the Collector into metadata/sources.json.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from pipeline.providers.base import BaseProvider, ProviderError, ProviderHealth
from pipeline.utils import now_utc

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class RssNewsProvider(BaseProvider):
    name = "rss_news"
    priority = 1
    domain = "news"

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        sources_cfg = self.settings.load_news_sources()
        self.sources = [s for s in sources_cfg.get("sources", []) if s.get("enabled", True)]
        self._client = httpx.Client(timeout=8.0, headers={"User-Agent": UA}, follow_redirects=True)
        # Source reachability: source_id → {"ok": bool, "error": str|None, "updated_at": str}
        self.source_status: dict[str, dict[str, Any]] = {}

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        if not self.sources:
            return ProviderHealth(provider=self.name, ok=False, error="no enabled sources", checked_at=None)
        try:
            items = self.fetch_news(max_items=1)
            ok = len(items) > 0
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "no items", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def fetch_news(self, max_items: int = 50) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        for source in self.sources:
            url = source.get("url", "")
            source_id = str(source.get("id", urlparse(url).netloc))
            try:
                raw = self._fetch_feed(url)
                self.source_status[source_id] = {"ok": True, "error": None, "updated_at": now_utc()}
                for entry in raw[:max_items]:
                    title = _clean_text(entry.get("title", ""))
                    link = entry.get("link", "")
                    published = _entry_date(entry)
                    if not title or not link:
                        continue
                    summary = _make_summary(entry)
                    items.append(
                        {
                            "title": title,
                            "source": str(source.get("name", source_id)),
                            "source_id": source_id,
                            "url": link,
                            "published_at": published,
                            "lang": source.get("lang", "en"),
                            "summary": summary,
                            "category_hint": source.get("category"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - a single source failure does not interrupt (degradation)
                self.source_status[source_id] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "updated_at": now_utc(),
                }
                errors.append(f"{source_id}: {type(exc).__name__}: {exc}")
                continue
        if not items and errors:
            raise ProviderError("RSS all sources failed: " + "; ".join(errors))
        return items

    def _fetch_feed(self, url: str) -> list[Any]:
        resp = self._client.get(url)
        if resp.status_code != 200:
            raise ProviderError(f"RSS HTTP {resp.status_code}")
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ProviderError(f"RSS parse failed: {feed.bozo_exception}")
        return feed.entries


def _clean_text(value: str) -> str:
    return " ".join((value or "").split())


def _entry_date(entry: Any) -> str:
    from datetime import datetime, timezone

    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            parsed = feedparser._parse_date(raw) if hasattr(feedparser, "_parse_date") else None
            if parsed:
                return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:  # noqa: BLE001
            continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_summary(entry: Any) -> str:
    """Self-written one-sentence summary: prefers the first sentence of description/summary, max 160 chars (copyright boundary)."""
    raw = entry.get("summary") or entry.get("description") or ""
    text = _clean_text(raw)
    # Strip HTML
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    first = text.split("。")[0].split(". ")[0] if text else ""
    return first[:160]
