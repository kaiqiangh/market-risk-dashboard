# MRD Automation Overview

Consolidated map of the **four WorkBuddy automations** that keep the Market Risk
Dashboard's `public/data` fresh and bilingual. All four are ACTIVE and run on the
**machine-local schedule (Dublin, Europe/Dublin — currently IST = UTC+1)**.

> Detailed procedures live in the sibling manuals:
> - Pipeline / data refresh → `docs/operations/scheduled-task.md`
> - AI bilingual briefs → `docs/operations/ai-analysis-automation.md`
>
> This file is the integration + status view; it does **not** restate those procedures.

---

## 1. The four automations at a glance

| Automation | ID | Dublin schedule | ET window | Role | Commit prefix |
|---|---|---|---|---|---|
| **Data Pipeline Refresh** | `automation-1785778453973` | **11:30 & 20:30** daily | 06:30 / 15:30 | Collects market + macro + crypto → writes the structured **fact layer** `facts.json`. **Does not** generate AI analysis. | `data:` |
| **Overnight News Refresh** | `automation-1785787482565` | **04:30** daily | 23:30 (prev. day) | News RSS only → `news.json` + `metadata/sources.json`. Touches no other dataset or analysis. | `data:` |
| **Pre-market AI Brief** | `automation-1785778436340` | **12:30** daily | 07:30 | Reads fresh `facts.json` (from 11:30 refresh) → bilingual `analysis.*.json` + full news translation. | `AI:` |
| **Post-market AI Brief** | `automation-1785778445021` | **21:30** daily | 16:30 | Same, post-market perspective (reads 20:30 refresh). | `AI:` |

The ET windows hold year-round (modulo US/EU DST-transition weeks). Each AI brief runs
**1h after** its data refresh, so it always reads the freshest `facts.json`.

---

## 2. How they complement each other (data flow)

The four tasks form a **contract-based daily loop**, not four independent jobs:

```
 04:30 News ──► news.json  (Asia-session news, independent of the pipeline)
                    │
 11:30 Pipeline ──► facts.json  (deterministic FACT layer: risk/macro/market/news_top/calendar/evidence)
                    │
 12:30 Pre-market Brief ──┐  reads facts.json
                          ├─► analysis.zh-CN.json + analysis.en.json
                          └─► news.zh-translations.json  (full-pair, every item in news.json)
                    │
 20:30 Pipeline ──► facts.json  (post-market refresh)
                    │
 21:30 Post-market Brief ──┐  reads facts.json
                            ├─► analysis.*.json + news.zh-translations.json
                            └─► runs --analysis-only: flips analysis→fresh, merges translations into news.json,
                                 updates metadata/freshness.json + metadata/translations.json
```

**The split that makes them complementary:**

- **Pipeline = the "fact layer" (deterministic, replayable).** Briefs = the "analysis + translation layer" (AI, pluggable). The pipeline **never** writes analysis files; the briefs **never** invent numbers outside `facts.json`. This is the architectural firewall.
- **Two pipeline runs bracket the two briefs:** 11:30 → 12:30 (pre-market), 20:30 → 21:30 (post-market). The brief's 1-hour offset guarantees it reads post-refresh facts.
- **News is refreshed out-of-band** at 04:30 so `news.json` stays current overnight; the briefs then translate **every** item (symmetric full pair, ADR-0003), which also acts as a catch-up/backfill pass for already-stored items.
- **Freshness is closed by the brief:** the pipeline marks analysis `freshness = degraded` after a `--full` run (because analysis isn't generated yet); the brief's `--analysis-only` step flips it back to `fresh` and merges translations. Single source of truth is preserved.

---

## 3. Verified run status (as of 2026-08-04 ~07:00 IST)

The four automations were created ~2026-08-03 18:34 IST (≈12.5h before this writing), so the
history is short. Findings below are from the run log + `git log` on `dev`.

**All recorded runs report `success = 1`.** ⚠️ Note: every run shows status `PENDING_REVIEW` —
this is the **WorkBuddy run-result review state (UI only)** and does **NOT** block the in-run
`git commit/push`. Proof that commits land:

```
a889c52  data: overnight news refresh 2026-08-04T03:27Z      (News 04:30 run)
c659ba1  data: re-backfill bilingual translations after overnight refresh (50/50)
5619a3c  AI: post-market bilingual brief 2026-08-03T20:30Z   (Post-market 21:30 run)
```

### End-to-end validated at a real scheduled slot ✅
| Automation | Scheduled | Actual run (IST) | Committed? |
|---|---|---|---|
| Overnight News Refresh | 04:30 | 04:25 (2026-08-04) | ✅ `a889c52` |
| Post-market AI Brief | 21:30 | 21:25 (2026-08-03) | ✅ `5619a3c` → merged via PR |

### Not yet observed at a real scheduled slot ⏳
| Automation | Status | Note |
|---|---|---|
| Pre-market AI Brief (12:30) | only a creation-time test run (18:57 IST 08-03) | first real slot = **2026-08-04 12:30** (future) |
| Data Pipeline Refresh (11:30/20:30) | only a creation-time test run (18:56 IST 08-03) | **20:30 slot on 2026-08-03 produced no run record and no `data: pipeline refresh` commit** → likely skipped/missed; next real slots = **11:30 & 20:30 on 2026-08-04** |

### Expected graceful degradation (not failures)
Run logs contain `403` (RSSHub public instance) and per-source `degraded` states. These are
**by design** — the pipeline walks the fallback chain (primary → fallback → last-good → degraded)
and continues. They do not abort the run.

---

## 4. Open items / to watch

1. **Pipeline first real slot (11:30, 2026-08-04):** confirm it fires and commits `data: pipeline refresh …`.
   If the 20:30 (08-03) miss was a "first occurrence skipped after creation" artefact, 11:30 should fire.
2. **Pre-market Brief (12:30, 2026-08-04):** confirm it fires and commits an `AI:` brief.
3. **`PENDING_REVIEW` gate:** decide whether the run-result review gate is desired, or should be relaxed.
   Note that commits already land regardless of this UI state.

---

## 5. References

- `docs/operations/scheduled-task.md` — pipeline CLI, cadence, failure degradation
- `docs/operations/ai-analysis-automation.md` — AI brief input/output contract, validation, drills
- `docs/adr/0003-bilingual-news-summary-model.md` — bilingual news/translation contract
