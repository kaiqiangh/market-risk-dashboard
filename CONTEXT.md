# Market Risk Dashboard

A dark-first market intelligence terminal: global macro risk scores, regimes, and evidence-driven AI briefs served as a static site. This glossary covers the design-system vocabulary introduced by the 2026-08 UI redesign; domain/market vocabulary lives in `docs/glossary.en.md`.

## Language

### Theme & Surfaces

**Theme preference**:
The user's stored theme choice: `dark` | `light` | `system`. Default is always `dark`, never `system` (ADR-0001). `system` follows `prefers-color-scheme` only when explicitly chosen.
_Avoid_: theme mode, appearance setting

**Surface level**:
Elevation expressed as one of three background lightness steps: `surface-0` (app background, open chart regions), `surface-1` (cards/panels), `surface-2` (overlays: popovers, tooltips, modals). Elevation is shown by lightness + 1px hairline border, never by shadow at rest.
_Avoid_: layer, z-depth, elevation shadow

**Glow budget**:
The design rule that luminous effects (shadows, glows, blur) are limited to focus rings and transient overlays only. Resting-state components have no shadow, no glass, no translucency.
_Avoid_: glow effect, glassmorphism

### Color Semantics

**Risk ramp**:
The `risk-*` token family (low / caution / high / severe / na), used exclusively for risk level and market regime. The only saturated colors at rest, so anomalies are immediately visible (ADR-0002).
_Avoid_: status colors, traffic-light colors

**Direction colors**:
The `dir-*` token family (up / down) for price/asset change. Deliberately muted relative to the risk ramp, always paired with an explicit sign. Global Western convention: green up, red down (ADR-0002).
_Avoid_: trend colors, profit/loss colors

**Freshness colors**:
The `fresh-*` treatment for data staleness: icon + text + muted styling; only stale/missing earn a warm tone. "Fresh" is the expected state and uses no saturated color.
_Avoid_: data quality colors

### Layout & Typography

**Open chart region**:
A chart rendered directly on `surface-0` under a section header, separated by hairline dividers — never wrapped in a card.
_Avoid_: chart card, chart panel

**Card policy**:
The rule that a card is allowed only for (a) KPI readouts or (b) widgets with independent freshness/status. Everything else is a hairline-divided section on `surface-0`.
_Avoid_: container, widget box

**Tabular numerals rule**:
All numeric readouts use `font-variant-numeric: tabular-nums`; true monospace is reserved for ticker symbols, IDs, timestamps, and citations.
_Avoid_: mono numbers, digital font

**AI brief**:
The LLM-generated research summary block, visually quarantined by a 2px accent left border + "AI" label, with inline evidence chips (source + timestamp) on every claim. Degraded AI renders an honest empty state.
_Avoid_: AI summary card, insights panel

## News data contract

**Source language**:
The language a news item's source feed emits, derived from `config/news_sources.yaml` `lang` (`en` | `zh`). Used only for translation routing; never stored as the display string.
_Avoid_: feed language, item language

**Canonical bilingual model**:
The rule that `title`/`summary` are always English and `title_zh`/`summary_zh` always Chinese for every NewsItem, regardless of source language. Chosen over a "mirror pair" so both UIs render correctly (ADR-0003).
_Avoid_: mirror pair, raw-language summary

**summary / summary_zh**:
`summary` is the English one-sentence summary (self-written, ≤160 chars, no full text — copyright boundary); `summary_zh` is its Chinese translation. Both populated per item.
_Avoid_: mixed-language summary, translation written into `summary`

**title / title_zh**:
`title` is the English headline; `title_zh` is the Chinese translation. Both populated per item.
_Avoid_: source-language title

**Translation merge**:
The pipeline step that applies `news.zh-translations.json` onto `news.json`. It copies `title_zh`/`summary_zh` (and the English side for zh-source items) **without overwriting** the canonical `summary`/`title` (ADR-0003).
_Avoid_: summary overwrite, in-place language flip
