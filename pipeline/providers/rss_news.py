"""News RSS Provider (architecture §1.3/§8.13 copyright boundary + Fix round R3 Chinese sources).

Only title/source/link/publish time/self-written summary are kept, not full text. The source list
comes from config/news_sources.yaml. Importance scoring (0-100) is done in NewsCollector
(source weight + keyword + asset hit + recency).

Degradation semantics (Fix rounds): a single failed/unreachable source → recorded in source_status
(degraded) → continue with other sources; ProviderError is raised only when ALL sources fail.
source_status is written by the Collector into metadata/sources.json.
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from pipeline.degrade import cache_max_age_hours
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
        degrade = self.settings.load_sources().get("degrade", {})
        self.max_retries = int(degrade.get("max_retries", 2))
        self.backoff_base = float(degrade.get("backoff_base_seconds", 1.0))
        self.jitter = bool(degrade.get("jitter", True))
        # #66: the cache cap is read from one place (pipeline.degrade.cache_max_age_hours).
        self.cache_max_age_hours = cache_max_age_hours()
        self.cache_dir = self.settings.artifacts_dir / "cache"
        # #102 (M-5): the news cap and the copyright-boundary summary cap are operations
        # knobs from sources.yaml:operations, not magic literals.
        operations = self.settings.load_sources_config().operations
        self.default_max_items = int(operations.news_max_items)
        self.summary_max_chars = int(operations.news_summary_max_chars)
        self._last_attempts = 0
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
            url = source.get("url", "")
            source_id = str(source.get("id", urlparse(url).netloc))
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
                self._save_source_cache(source_id, fetched_at, normalized)
                self.source_status[source_id] = {
                    "ok": True,
                    "degraded": False,
                    "from_cache": False,
                    "error": None,
                    "attempts": self._last_attempts,
                    "item_count": len(normalized),
                    "invalid_entries": invalid_entries,
                    "last_good_at": fetched_at,
                    "updated_at": fetched_at,
                }
                items.extend(normalized)
            except Exception as exc:  # noqa: BLE001 - a single source failure does not interrupt (degradation)
                cached = self._load_source_cache(source_id)
                status = {
                    "ok": False,
                    "degraded": True,
                    "from_cache": bool(cached),
                    "error": f"{type(exc).__name__}: {exc}",
                    "attempts": self._last_attempts,
                    "updated_at": now_utc(),
                }
                if cached:
                    cached_items, cached_at, age_hours = cached
                    items.extend(cached_items[:max_items])
                    status.update(
                        last_good_at=cached_at,
                        cache_age_hours=round(age_hours, 2),
                        item_count=len(cached_items),
                    )
                self.source_status[source_id] = status
                errors.append(f"{source_id}: {type(exc).__name__}: {exc}")
                continue
        if not items and errors:
            raise ProviderError("RSS all sources failed: " + "; ".join(errors))
        return items

    def _fetch_feed(self, url: str) -> list[Any]:
        for attempt in range(self.max_retries + 1):
            self._last_attempts = attempt + 1
            try:
                resp = self._client.get(url)
            except httpx.RequestError:
                if attempt >= self.max_retries:
                    raise
                _sleep_before_retry(attempt, self.backoff_base, self.jitter)
                continue
            if resp.status_code != 200:
                retryable = resp.status_code in {408, 425, 429} or 500 <= resp.status_code <= 599
                if retryable and attempt < self.max_retries:
                    _sleep_before_retry(attempt, self.backoff_base, self.jitter)
                    continue
                raise ProviderError(f"RSS HTTP {resp.status_code}")
            if not resp.content.strip():
                raise ProviderError("RSS empty response body")
            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                raise ProviderError(f"RSS parse failed: {feed.bozo_exception}")
            return feed.entries
        raise ProviderError("RSS request exhausted retries")

    def _source_cache_path(self, source_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id)
        return self.cache_dir / f"rss__{safe_id}.json"

    def _save_source_cache(self, source_id: str, fetched_at: str, items: list[dict[str, Any]]) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._source_cache_path(source_id).write_text(
                json.dumps({"fetched_at": fetched_at, "items": items}, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _load_source_cache(self, source_id: str) -> tuple[list[dict[str, Any]], str, float] | None:
        path = self._source_cache_path(source_id)
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = str(cached["fetched_at"])
            cached_items = cached["items"]
            if not isinstance(cached_items, list):
                return None
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age_hours = max(0.0, (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0)
            if age_hours > self.cache_max_age_hours:
                return None
            return cached_items, fetched_at, age_hours
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            return None


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


def _normalize_entry(entry: Any, source: dict[str, Any], source_id: str, max_chars: int = 160) -> dict[str, Any] | None:
    title = _clean_text(entry.get("title", ""))
    link = str(entry.get("link", "")).strip()
    published = _entry_date(entry)
    parsed_link = urlparse(link)
    if not title or not published or parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
        return None
    return {
        "title": title,
        "source": str(source.get("name", source_id)),
        "source_id": source_id,
        "url": link,
        "published_at": published,
        "lang": source.get("lang", "en"),
        "summary": _make_summary(entry, max_chars=max_chars),
        "category_hint": source.get("category"),
    }


def _sleep_before_retry(attempt: int, backoff_base: float, jitter: bool) -> None:
    delay = backoff_base * (2**attempt)
    if jitter:
        delay *= 0.5 + random.random()
    time.sleep(delay)


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
