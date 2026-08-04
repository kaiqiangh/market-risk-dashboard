"""Bilingual canonical model tests (issue #36).

Covers:
- NewsItem accepts the additive `summary_zh` field (canonical bilingual contract)
- NewsTranslation accepts the symmetric full pair (title/summary EN + title_zh/summary_zh ZH)
- merge_translations never overwrites the canonical English `summary`; copies both sides
- zh-source items receive an English `summary` from the translation record, `summary_zh` keeps the Chinese original
- missing / absent translations are a no-op (graceful degradation)

Seam: the data contract + the merge step (pipeline/collectors/news.py merge_translations).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pipeline.collectors.news import NewsCollector
from pipeline.schemas import NewsDataset, NewsEnvelope, NewsItem, NewsTranslation, NewsTranslationsDataset
from pipeline.schemas.envelope import SCHEMA_VERSION

UTC = "2026-08-03T00:00:00Z"


def _item(**overrides) -> NewsItem:
    base = dict(
        id="a",
        title="Fed raises rates",
        title_zh=None,
        source="Federal Reserve",
        url="https://example.com/x",
        published_at=UTC,
        categories=[],
        assets=[],
        importance=50.0,
        sentiment=None,
        summary="Fed raised rates by 25bp",
        impact_window=None,
    )
    base.update(overrides)
    return NewsItem(**base)


def _envelope(items: list[NewsItem]) -> NewsEnvelope:
    return NewsEnvelope(
        generated_at=UTC,
        schema_version=SCHEMA_VERSION,
        source=["rss_news"],
        source_updated_at=UTC,
        freshness_status="fresh",
        data_quality=1.0,
        payload=NewsDataset(items=items, total=len(items), updated_at=UTC),
    )


def _translations(*items: NewsTranslation) -> NewsTranslationsDataset:
    return NewsTranslationsDataset(items=list(items), updated_at=UTC)


def _collector() -> NewsCollector:
    return NewsCollector(registry=None)


# ---- NewsItem schema: additive summary_zh (canonical bilingual contract) ----

def test_news_item_accepts_summary_zh():
    item = _item(summary_zh="美联储加息25个基点")
    assert item.summary_zh == "美联储加息25个基点"
    assert item.summary == "Fed raised rates by 25bp"  # canonical English untouched


def test_news_item_summary_zh_defaults_to_none_when_absent():
    item = _item()
    assert item.summary_zh is None


def test_news_item_lang_defaults_to_en_and_accepts_zh():
    assert _item().lang == "en"
    assert _item(lang="zh").lang == "zh"


# ---- NewsTranslation schema: symmetric full pair ----

def test_news_translation_accepts_symmetric_full_pair():
    t = NewsTranslation(
        id="a",
        title="Fed raises rates",
        summary="Fed raised rates by 25bp",
        title_zh="美联储加息",
        summary_zh="美联储加息25个基点",
    )
    assert t.title == "Fed raises rates"
    assert t.summary == "Fed raised rates by 25bp"
    assert t.title_zh == "美联储加息"
    assert t.summary_zh == "美联储加息25个基点"


def test_news_translation_legacy_shape_still_parses():
    # Old automation output {id, title_zh, summary_zh?} must remain valid.
    t = NewsTranslation(id="a", title_zh="美联储加息")
    assert t.title is None
    assert t.summary is None
    assert t.summary_zh is None


# ---- merge_translations: no overwrite of canonical English ----

def test_merge_keeps_en_summary_and_sets_summary_zh():
    news = _envelope([_item(id="a")])
    trans = _translations(
        NewsTranslation(
            id="a",
            title="Fed raises rates",
            summary="Fed raised rates by 25bp",
            title_zh="美联储加息",
            summary_zh="美联储加息25个基点",
        )
    )
    merged = _collector().merge_translations(news, trans)
    item = merged.payload.items[0]
    assert item.summary == "Fed raised rates by 25bp"  # not overwritten with Chinese
    assert item.title == "Fed raises rates"
    assert item.summary_zh == "美联储加息25个基点"
    assert item.title_zh == "美联储加息"


def test_merge_zh_source_gets_english_summary_and_keeps_chinese_original():
    news = _envelope([_item(id="z", lang="zh", source="东方财富", title="全球市场收跌", summary="美股三大指数收跌")])
    trans = _translations(
        NewsTranslation(
            id="z",
            title="Global markets fell",
            summary="US stocks fell across the board",
            title_zh="全球市场收跌",
            summary_zh="美股三大指数收跌",
        )
    )
    merged = _collector().merge_translations(news, trans)
    item = merged.payload.items[0]
    assert item.summary == "US stocks fell across the board"  # English canonical filled
    assert item.summary_zh == "美股三大指数收跌"  # Chinese original preserved
    assert item.title == "Global markets fell"
    assert item.title_zh == "全球市场收跌"


def test_merge_untranslated_item_is_unchanged():
    news = _envelope([_item(id="a"), _item(id="b", title="Second item", summary="Second summary")])
    trans = _translations(NewsTranslation(id="a", title_zh="美联储加息", summary_zh="美联储加息25个基点"))
    merged = _collector().merge_translations(news, trans)
    kept = merged.payload.items[1]
    assert kept.id == "b"
    assert kept.summary == "Second summary"
    assert kept.summary_zh is None
    assert kept.title_zh is None


def test_merge_never_overwrites_canonical_english_when_record_diverges():
    # A translation record must never silently rewrite the canonical English of an item. The
    # inequality guard restricts English-side writes to zh-source items (raw Chinese → English).
    news = _envelope([_item(id="a")])
    trans = _translations(
        NewsTranslation(id="a", title="Reworded title", summary="Reworded English summary", title_zh="美联储加息", summary_zh="中文摘要")
    )
    merged = _collector().merge_translations(news, trans)
    item = merged.payload.items[0]
    assert item.summary == "Fed raised rates by 25bp"  # canonical English protected
    assert item.title == "Fed raises rates"
    assert item.summary_zh == "中文摘要"  # Chinese side still overlaid


def test_merge_none_translations_is_noop():
    news = _envelope([_item(id="a")])
    merged = _collector().merge_translations(news, None)
    assert merged is news
    assert merged.payload.items[0].summary_zh is None
