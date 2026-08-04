"""RSS source health, retry, validation, and last-good cache checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.collectors.news import NewsCollector
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
    provider.sources = [{"id": "test", "name": "Test", "url": "https://example.com/feed", "lang": "en"}]
    provider.max_retries = 1
    provider.backoff_base = 0
    provider.jitter = False
    return provider


def test_transient_http_failure_retries_per_source(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path)
    responses = iter([(503, b"busy"), (200, b"<rss />")])
    calls = {"count": 0}

    class Client:
        def get(self, _url):
            calls["count"] += 1
            status, content = next(responses)
            return type("Response", (), {"status_code": status, "content": content})()

    provider._client = Client()
    monkeypatch.setattr("pipeline.providers.rss_news.feedparser.parse", lambda _content: type("Feed", (), {"bozo": False, "entries": [ENTRY]})())
    assert len(provider.fetch_news()) == 1
    assert calls["count"] == 2
    assert provider.source_status["test"]["ok"] is True


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


def test_failed_source_uses_fresh_last_good_cache_and_stays_degraded(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path)
    monkeypatch.setattr(provider, "_fetch_feed", lambda _url: [ENTRY])
    assert len(provider.fetch_news()) == 1

    def fail(_url):
        raise ProviderError("temporary outage")

    monkeypatch.setattr(provider, "_fetch_feed", fail)
    assert len(provider.fetch_news()) == 1
    status = provider.source_status["test"]
    assert status["ok"] is False
    assert status["from_cache"] is True
    assert status["cache_age_hours"] < 1


def test_missing_date_is_rejected_instead_of_using_now(tmp_path, monkeypatch) -> None:
    provider = _provider(tmp_path)
    provider.max_retries = 0
    monkeypatch.setattr(provider, "_fetch_feed", lambda _url: [{"title": "No date", "link": ENTRY["link"]}])
    with pytest.raises(ProviderError, match="no valid entries"):
        provider.fetch_news()


class _NewsProvider:
    source_status = {
        "good": {"ok": True, "degraded": False},
        "bad": {"ok": False, "degraded": True, "error": "HTTP 503"},
    }


class _Registry:
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
            "meta": {"provider": "rss_news"},
        }


def test_collector_propagates_partial_source_failure_to_news_freshness() -> None:
    news, meta = NewsCollector(_Registry()).collect()
    assert news.freshness_status == "degraded"
    assert news.data_quality == 0.8
    assert meta["degraded"]
    assert meta["source_status"]["bad"]["ok"] is False
