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
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from pipeline.config.models import NewsSource
from pipeline.providers.base import BaseProvider, ProviderError, ProviderHealth, guarded_client, redact
from pipeline.utils import now_utc

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class RssNewsProvider(BaseProvider):
    name = "rss_news"
    domain = "news"
    hosts = ("rss",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        # #102: sources come from the VALIDATED news_sources config (single shape,
        # extra="forbid"); per-source `enabled` is preserved by the model.
        self.sources = [s for s in self.settings.load_news_sources_config().sources if s.enabled]
        # S-3: outbound allowlist = the synthetic bucket + every configured source host;
        # sources marked `trust: relay` (rsshub.app) vouch for their redirect targets.
        allowed = set(self.hosts) | {
            urlparse(s.url).hostname for s in self.sources if urlparse(s.url).hostname
        }
        relay_hosts = {
            urlparse(s.url).hostname for s in self.sources if s.trust == "relay" and urlparse(s.url).hostname
        }
        self._client = guarded_client(
            allowed, timeout=8.0, headers={"User-Agent": UA}, relay_hosts=relay_hosts
        )
        # #102 (M-5): the news cap and the copyright-boundary summary cap are operations
        # knobs from sources.yaml:operations, not magic literals.
        operations = self.settings.load_sources_config().operations
        self.default_max_items = int(operations.news_max_items)
        self.summary_max_chars = int(operations.news_summary_max_chars)
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

    def fetch_news(self, max_items: int | None = None) -> list[dict[str, Any]]:
        if max_items is None:
            max_items = self.default_max_items
        items: list[dict[str, Any]] = []
        errors: list[str] = []
        self.source_status = {}
        for source in self.sources:
            url = source.url
            source_id = str(source.id or urlparse(url).netloc)
            try:
                raw = self._fetch_feed(url)
                normalized: list[dict[str, Any]] = []
                invalid_entries = 0
                for entry in raw[:max_items]:
                    item = _normalize_entry(entry, source, source_id, max_chars=self.summary_max_chars)
                    if item is None:
                        invalid_entries += 1
                        continue
                    normalized.append(item)
                if not normalized:
                    raise ProviderError(f"RSS source returned no valid entries ({invalid_entries} invalid)")
                fetched_at = now_utc()
                # #103/D-6: no per-source cache here — the registry's last-good cache and the
                # single retry layer cover the whole news domain. Per-source health is still
                # reported for the status page.
                self.source_status[source_id] = {
                    "ok": True,
                    "degraded": False,
                    "from_cache": False,
                    "error": None,
                    "item_count": len(normalized),
                    "invalid_entries": invalid_entries,
                    "last_good_at": fetched_at,
                    "updated_at": fetched_at,
                }
                items.extend(normalized)
            except Exception as exc:  # noqa: BLE001 - a single source failure does not interrupt (degradation)
                self.source_status[source_id] = {
                    "ok": False,
                    "degraded": True,
                    "from_cache": False,
                    "error": redact(f"{type(exc).__name__}: {exc}"),
                    "updated_at": now_utc(),
                }
                errors.append(f"{source_id}: {redact(str(exc))}")
                continue
        if not items and errors:
            raise ProviderError("RSS all sources failed: " + "; ".join(errors))
        return items

    def _fetch_feed(self, url: str) -> list[Any]:
        """Single-attempt fetch (#103/D-6): classification at the one boundary, retries in
        ProviderRegistry.call — the per-source retry loop and per-source cache are gone."""
        try:
            resp = self._client.get(url)
        except httpx.RequestError as exc:
            raise ProviderError.from_exception(exc, detail=f"RSS {url}") from exc
        if resp.status_code != 200:
            raise ProviderError.from_exception(
                httpx.HTTPStatusError(f"RSS HTTP {resp.status_code}", request=resp.request, response=resp),
                detail=f"RSS HTTP {resp.status_code}",
            )
        if not resp.content.strip():
            raise ProviderError("RSS empty response body")
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ProviderError(f"RSS parse failed: {feed.bozo_exception}")
        return feed.entries


def _clean_text(value: str) -> str:
    return " ".join((value or "").split())


def _entry_date(entry: Any) -> str | None:
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            parser = getattr(feedparser, "_parse_date", None) or getattr(feedparser.datetimes, "_parse_date", None)
            parsed = parser(raw) if parser else None
            if parsed:
                if hasattr(parsed, "tm_year"):
                    parsed = datetime(*parsed[:6], tzinfo=timezone.utc)
                elif parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:  # noqa: BLE001
            continue
    return None


def _normalize_entry(entry: Any, source: "NewsSource", source_id: str, max_chars: int = 160) -> dict[str, Any] | None:
    title = _clean_text(entry.get("title", ""))
    link = str(entry.get("link", "")).strip()
    published = _entry_date(entry)
    parsed_link = urlparse(link)
    if not title or not published or parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
        return None
    return {
        "title": title,
        "source": str(source.name or source_id),
        "source_id": source_id,
        "url": link,
        "published_at": published,
        "lang": source.lang,
        "summary": _make_summary(entry, max_chars=max_chars),
        "category_hint": source.category,
    }


def _make_summary(entry: Any, max_chars: int = 160) -> str:
    """Self-written one-sentence summary: prefers the first sentence of description/summary, max ``max_chars`` chars (copyright boundary, #102 M-5)."""
    raw = entry.get("summary") or entry.get("description") or ""
    text = _clean_text(raw)
    # Strip HTML
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    text = " ".join(text.split())
    first = text.split("。")[0].split(". ")[0] if text else ""
    return first[:max_chars]
