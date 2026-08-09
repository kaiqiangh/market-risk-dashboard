"""RSS source health, retry, validation, and last-good cache checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.collectors.news import NewsCollector
from pipeline.config.models import NewsSource
from pipeline.providers.base import ProviderError
from pipeline.providers.rss_news import RssNewsProvider
from pipeline.settings import Settings


ENTRY = {
    "title": "Fed keeps rates steady",
    "link": "https://example.com/fed",
    "published": "Mon, 03 Aug 2026 10:00:00 GMT",
    "summary": "The Federal Reserve kept rates steady.",
}


def _provider(tmp_path: Path) -> RssNewsProvider:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)
    provider = RssNewsProvider(settings)
    provider.sources = [NewsSource(id="test", name="Test", url="https://example.com/feed", lang="en")]
    provider.max_retries = 1
    provider.backoff_base = 0
    provider.jitter = False
    # #102: the provider resolves its cache dir from sources.yaml:degrade.last_good_cache_dir
    # (project-rooted). Tests override it to their own tmp_path so per-source cache entries
    # cannot leak across tests via the shared repo artifacts/cache.
    provider.cache_dir = tmp_path / "cache"
    return provider


def test_transient_http_failure_does_not_retry_inside_provider(tmp_path, monkeypatch) -> None:
    """#103/D-6: the per-source retry loop is gone — a single attempt, one call.

    Retries now live in ProviderRegistry.call (the one retry layer, E-3); a direct
    fetch_news() call surfaces the failure after exactly one HTTP attempt.
    """
    provider = _provider(tmp_path)
    calls = {"count": 0}

    class Client:
        def get(self, _url):
            calls["count"] += 1
            return type("Response", (), {"status_code": 503, "content": b"busy"})()

    provider._client = Client()
    with pytest.raises(ProviderError, match="all sources failed"):
        provider.fetch_news()
    assert calls["count"] == 1
    assert provider.source_status["test"]["ok"] is False


def test_auth_failure_does_not_retry(tmp_path) -> None:
    provider = _provider(tmp_path)
    calls = {"count": 0}

    class Client:
        def get(self, _url):
            calls["count"] += 1
            return type("Response", (), {"status_code": 404, "content": b"missing"})()

    provider._client = Client()
    with pytest.raises(ProviderError, match="all sources failed"):
        provider.fetch_news()
    assert calls["count"] == 1
    assert provider.source_status["test"]["ok"] is False


def test_failed_source_is_reported_degraded_without_per_source_cache(tmp_path, monkeypatch) -> None:
    """#103/D-6: per-source last-good cache removed — a source outage is degraded, not replayed."""
    provider = _provider(tmp_path)
    monkeypatch.setattr(provider, "_fetch_feed", lambda _url: ([ENTRY], None))
    assert len(provider.fetch_news()) == 1

    def fail(_url):
        raise ProviderError("temporary outage")

    monkeypatch.setattr(provider, "_fetch_feed", fail)
    with pytest.raises(ProviderError, match="all sources failed"):
        provider.fetch_news()
    status = provider.source_status["test"]
    assert status["ok"] is False
    assert status["from_cache"] is False


def test_missing_date_is_rejected_instead_of_using_now(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path)
    monkeypatch.setattr(
        provider, "_fetch_feed",
        lambda _url: ([{"title": "No date", "link": ENTRY["link"]}], None),
    )
    with pytest.raises(ProviderError, match="no valid entries"):
        provider.fetch_news()


class _NewsProvider:
    source_status = {
        "good": {"ok": True, "degraded": False},
        "bad": {"ok": False, "degraded": True, "error": "HTTP 503"},
    }


class _Registry:
    def __init__(self) -> None:
        self.degraded_domains: set[str] = set()

    def providers_for(self, domain):
        return [_NewsProvider()] if domain == "news" else []

    def call(self, *_args, **_kwargs):
        return {
            "result": [
                {
                    "title": ENTRY["title"],
                    "source": "Test",
                    "source_id": "good",
                    "url": ENTRY["link"],
                    "published_at": "2026-08-03T10:00:00Z",
                    "lang": "en",
                    "summary": "Rates stayed steady.",
                }
            ],
            "meta": {"provider": "rss_news", "used_fallback": False, "from_cache": False},
        }


class _CachedRegistry(_Registry):
    def call(self, *_args, **_kwargs):
        result = super().call(*_args, **_kwargs)
        result["meta"]["from_cache"] = True
        return result


def test_collector_propagates_partial_source_failure_to_news_freshness() -> None:
    """A partial source failure reaches the caller's freshness determination.

    #64/#65: the collector no longer assigns freshness_status — it reports the provider
    outcome (meta["degraded"]), and the single assembly path turns that into a degraded
    envelope. Published quality is driven by the collector's local source outcome, even
    when the registry has no global degraded marker.
    """
    from pipeline.schemas import NewsEnvelope
    from pipeline.schemas.envelope import assemble_envelope

    registry = _Registry()
    news, meta = NewsCollector(registry).collect()
    assert meta["degraded"]
    assert meta["data_quality"] == 0.8
    assert meta["source_status"]["bad"]["ok"] is False

    outcome = meta["provider_outcome"]
    env = assemble_envelope(
        NewsEnvelope, news, dataset="news", degraded=meta["degraded"],
        provider=outcome["provider"],
        used_fallback=outcome["used_fallback"],
        from_cache=outcome["from_cache"],
        data_quality=meta["data_quality"],
    )
    assert env.freshness_status == "degraded"

    # An unrelated registry marker does not change the local news quality.
    registry.degraded_domains.add("news")
    _, degraded_meta = NewsCollector(registry).collect()
    assert degraded_meta["data_quality"] == 0.8

    _, cached_meta = NewsCollector(_CachedRegistry()).collect()
    assert cached_meta["data_quality"] == 0.8


# -------------------------------------------------------------------------------------
# #124/#126: per-source fallback URL chain — one try per URL, first success wins
# -------------------------------------------------------------------------------------

FEED_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<rss version="2.0"><channel><title>Test feed</title>'
    "<item><title>Fallback headline</title><link>https://example.com/fb</link>"
    "<pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate>"
    "<description>Fallback summary text.</description></item>"
    "</channel></rss>"
)


class ScriptedClient:
    """Fake HTTP client: each URL is scripted to a (status, content) response."""

    def __init__(self, responses: dict[str, tuple[int, bytes]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str):
        self.calls.append(url)
        status, content = self.responses[url]
        return type("Response", (), {"status_code": status, "content": content, "request": None})()


def _chained_provider(tmp_path: Path) -> RssNewsProvider:
    provider = _provider(tmp_path)
    provider.sources = [
        NewsSource(
            id="test", name="Test", url="https://primary.example/feed", lang="en",
            fallback_urls=["https://fallback.example/feed"],
        )
    ]
    return provider


def test_fallback_serves_when_primary_url_fails(tmp_path: Path) -> None:
    """#124/#126: primary 403 → the source serves from its fallback and is reported ok."""
    provider = _chained_provider(tmp_path)
    provider._client = ScriptedClient({
        "https://primary.example/feed": (403, b"<html>denied</html>"),
        "https://fallback.example/feed": (200, FEED_XML.encode()),
    })

    items = provider.fetch_news()

    assert len(items) == 1
    assert items[0]["title"] == "Fallback headline"
    assert provider._client.calls == ["https://primary.example/feed", "https://fallback.example/feed"]
    status = provider.source_status["test"]
    assert status["ok"] is True
    assert status["degraded"] is False


def test_first_success_short_circuits_fallback(tmp_path: Path) -> None:
    """#124/#126: a healthy primary means the fallback is never contacted."""
    provider = _chained_provider(tmp_path)
    provider._client = ScriptedClient({
        "https://primary.example/feed": (200, FEED_XML.encode()),
        "https://fallback.example/feed": (200, FEED_XML.encode()),
    })

    items = provider.fetch_news()

    assert len(items) == 1
    assert provider._client.calls == ["https://primary.example/feed"]
    assert provider.source_status["test"]["ok"] is True


def test_entire_chain_failure_marks_source_degraded(tmp_path: Path) -> None:
    """#124/#126: every URL failed → the source is degraded with the last error."""
    provider = _chained_provider(tmp_path)
    provider._client = ScriptedClient({
        "https://primary.example/feed": (403, b"<html>denied</html>"),
        "https://fallback.example/feed": (403, b"<html>denied</html>"),
    })

    with pytest.raises(ProviderError, match="all sources failed"):
        provider.fetch_news()

    assert provider._client.calls == ["https://primary.example/feed", "https://fallback.example/feed"]
    status = provider.source_status["test"]
    assert status["ok"] is False
    assert status["degraded"] is True
    assert "403" in status["error"]


CHANNEL_FEED_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<rss version="2.0"><channel><title>Test feed</title><link>https://www.cls.cn/telegraph</link>'
    "<item><title>Linkless flash</title>"
    "<pubDate>Mon, 03 Aug 2026 10:00:00 GMT</pubDate>"
    "<description>Flash summary text.</description></item>"
    "</channel></rss>"
)


def test_linkless_entries_fall_back_to_channel_link(tmp_path: Path) -> None:
    """#127: 财联社 telegraph entries carry no link; a linkless item falls back to the
    feed's channel link (a valid 'view source' URL) instead of being dropped."""
    provider = _provider(tmp_path)
    provider.sources = [NewsSource(id="test", name="Test", url="https://hub.example/cls", lang="zh")]
    provider._client = ScriptedClient({
        "https://hub.example/cls": (200, CHANNEL_FEED_XML.encode()),
    })

    items = provider.fetch_news()

    assert len(items) == 1
    assert items[0]["title"] == "Linkless flash"
    assert items[0]["url"] == "https://www.cls.cn/telegraph"
    assert provider.source_status["test"]["ok"] is True


def test_linkless_item_without_channel_link_is_rejected(tmp_path: Path) -> None:
    """#127: no entry link AND no channel link → the item is dropped (no fake URL)."""
    provider = _provider(tmp_path)
    provider.sources = [NewsSource(id="test", name="Test", url="https://hub.example/cls", lang="zh")]
    provider._client = ScriptedClient({
        "https://hub.example/cls": (200, FEED_XML.replace("<link>https://example.com/fb</link>", "").encode()),
    })

    with pytest.raises(ProviderError, match="no valid entries"):
        provider.fetch_news()
    assert provider.source_status["test"]["ok"] is False
