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

from pipeline.collectors.news import NewsCollector
from pipeline.schemas import NewsDataset, NewsItem, NewsTranslation, NewsTranslationsDataset

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


def _payload(items: list[NewsItem]) -> NewsDataset:
    """The news payload (#64): collectors return payloads; the caller assembles the envelope."""
    return NewsDataset(items=items, total=len(items), updated_at=UTC)


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
    news = _payload([_item(id="a")])
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
    item = merged.items[0]
    assert item.summary == "Fed raised rates by 25bp"  # not overwritten with Chinese
    assert item.title == "Fed raises rates"
    assert item.summary_zh == "美联储加息25个基点"
    assert item.title_zh == "美联储加息"


def test_merge_zh_source_gets_english_summary_and_keeps_chinese_original():
    news = _payload([_item(id="z", lang="zh", source="东方财富", title="全球市场收跌", summary="美股三大指数收跌")])
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
    item = merged.items[0]
    assert item.summary == "US stocks fell across the board"  # English canonical filled
    assert item.summary_zh == "美股三大指数收跌"  # Chinese original preserved
    assert item.title == "Global markets fell"
    assert item.title_zh == "全球市场收跌"


def test_merge_untranslated_item_is_unchanged():
    news = _payload([_item(id="a"), _item(id="b", title="Second item", summary="Second summary")])
    trans = _translations(NewsTranslation(id="a", title_zh="美联储加息", summary_zh="美联储加息25个基点"))
    merged = _collector().merge_translations(news, trans)
    kept = merged.items[1]
    assert kept.id == "b"
    assert kept.summary == "Second summary"
    assert kept.summary_zh is None
    assert kept.title_zh is None


def test_merge_never_overwrites_canonical_english_when_record_diverges():
    # A translation record must never silently rewrite the canonical English of an item. The
    # inequality guard restricts English-side writes to zh-source items (raw Chinese → English).
    news = _payload([_item(id="a")])
    trans = _translations(
        NewsTranslation(id="a", title="Reworded title", summary="Reworded English summary", title_zh="美联储加息", summary_zh="中文摘要")
    )
    merged = _collector().merge_translations(news, trans)
    item = merged.items[0]
    assert item.summary == "Fed raised rates by 25bp"  # canonical English protected
    assert item.title == "Fed raises rates"
    assert item.summary_zh == "中文摘要"  # Chinese side still overlaid


def test_merge_none_translations_is_noop():
    news = _payload([_item(id="a")])
    merged = _collector().merge_translations(news, None)
    assert merged is news
    assert merged.items[0].summary_zh is None

def test_merge_falls_back_to_title_match_on_id_drift():
    # #225: the AI step re-derives ids, so a translation with a different id must still land
    # on its article when the normalized Chinese title matches (zh-source item).
    news = _payload(
        [_item(id="collector-1", lang="zh", source="东方财富", title="美联储决议：利率维持不变", summary="美联储维持利率不变。")]
    )
    trans = _translations(
        NewsTranslation(
            id="ai-1", title="Fed holds rates steady", summary="The Fed held rates unchanged.",
            title_zh="美联储决议：利率维持不变", summary_zh="美联储维持利率不变。",
        )
    )
    merged = _collector().merge_translations(news, trans)
    item = merged.items[0]
    assert item.title == "Fed holds rates steady"  # English canonical backfilled despite id drift
    assert item.summary == "The Fed held rates unchanged."
    assert item.title_zh == "美联储决议：利率维持不变"
    assert item.summary_zh == "美联储维持利率不变。"


def test_merge_title_fallback_en_source_overlays_chinese():
    # #225: id drift on an en-source item still overlays the Chinese side via English title match.
    news = _payload([_item(id="collector-2", title="Fed raises rates", summary="Fed raised rates by 25bp")])
    trans = _translations(
        NewsTranslation(
            id="ai-2", title="Fed raises rates", summary="Fed raised rates by 25bp",
            title_zh="美联储加息", summary_zh="美联储加息25个基点",
        )
    )
    merged = _collector().merge_translations(news, trans)
    item = merged.items[0]
    assert item.title == "Fed raises rates"  # canonical English untouched
    assert item.title_zh == "美联储加息"
    assert item.summary_zh == "美联储加息25个基点"
