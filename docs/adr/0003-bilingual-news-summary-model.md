---
status: accepted
---

# Bilingual canonical language model for NewsItem

NewsItem is rendered in two locales (zh-CN + en). We adopt a **canonical bilingual model**: `title` and `summary` are always English; `title_zh` and `summary_zh` are always Chinese. The source feed's own language is recorded per item (derived from `config/news_sources.yaml` `lang`) but is never stored as the display string.

This replaces the previous "mirror pair" design, where `summary`/`title` held the raw feed language and `summary_zh` was an optional overlay that `merge_translations` wrote *into* `summary` (`pipeline/collectors/news.py:161`). That overwrite — applied only on partial translation coverage — was the root cause of `summary` coming out sometimes Chinese, sometimes English, and it also broke the English UI (NewsCard rendered `summary` for every locale).

## Considered options

- **Mirror pair** — `summary` = raw feed language, `summary_zh` = translation. Rejected: Chinese-source items (东方财富 / 财联社 / 华尔街见闻) have no English text, so the English UI shows Chinese; it also preserves mixed-language at storage.
- **Canonical bilingual** (`summary`=EN, `summary_zh`=ZH) — **chosen**: symmetric, both UIs render correctly, and it removes the overwrite bug.
- **Single-language normalization** — force every `summary` to Chinese, drop translation. Rejected: abandons the en locale.

## Consequences

- **`NewsTranslation` (news.zh-translations.json) becomes a symmetric full-pair record.** It carries both `title`/`summary` (English) and `title_zh`/`summary_zh` (Chinese) for the same id. Merge copies both sides; it no longer needs to inspect source language.
- **Translation automation must emit both directions** — en→zh for English sources, zh→en for Chinese sources — and aim for full coverage (best-effort + graceful fallback, not partial).
- **`merge_translations` must stop overwriting `summary`.** It only sets `summary_zh`/`title_zh` (and the English side when the source is Chinese). The UI falls back to the other language when the preferred one is missing; it never blanks a card.
- **Schema change** in `pipeline/schemas/news.py` (add `summary_zh` to `NewsItem`, redefine `summary` semantics) and `src/schemas/news.ts`.
- **Historical items** without translations need a backfill pass.
- **Source language** (`lang` from `config/news_sources.yaml`) is retained only for translation routing, never as the stored display string.
