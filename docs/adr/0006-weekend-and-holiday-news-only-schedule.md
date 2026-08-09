# Weekend is news-only; holidays gate per market

The five MRD automations ran `FREQ=DAILY` — every day of the week, at 04:30 / 11:30 / 12:30 / 20:30 / 21:30 Dublin. On Saturdays and Sundays that meant the pre-market brief summarized a closed market, the post-market brief summarized a market that never opened, and both pipeline refreshes fetched flat sessions and committed Friday's numbers twice. Work nobody reads, produced on schedule. The request was simple: weekends run only the news refresh. The same reasoning one day removed is an exchange holiday — a Thursday on which the NYSE never opens deserves the same treatment as a Sunday, and the RRULE language cannot express either "not Saturday" or "not Thanksgiving". So the two problems get two mechanisms:

- **Weekends are excluded by schedule.** The four market-sensitive tasks fire `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` — on a Saturday or Sunday the trigger never happens, nothing starts, nothing skips. This is the "completely skipped" guarantee, enforced by the scheduler itself.
- **Holidays are handled by an in-task gate.** Each market-sensitive task runs a trading-day check as step 0: `python -m pipeline.schedule.trading_day --market cn|us` exits 0 (trading day — proceed) or 3 (exchange closed — log one line, exit 0, no data writes, no commit).

The news refresh is the exception that defines the policy: it stays `FREQ=DAILY` and runs every day including weekends, because news is the one dataset that does not go quiet when a market does.

## Per-pair calendars, not a blanket rule

The two pipeline runs exist for different markets, and the prompts already said so (#98): the 11:30 Dublin run lands after the CN close to capture the **fresh A-share close**; the 20:30 Dublin run lands after the US close to capture the **fresh US close**. The briefs hang off their respective refresh. So the gate is keyed per pair:

| Automation pair | Market clock | Gate |
|---|---|---|
| 11:30 pipeline → 12:30 pre-market brief | CN session (fresh A-share close) | SSE (XSHG) |
| 20:30 pipeline → 21:30 post-market brief | US session (fresh US close) | NYSE (XNYS) |

A blanket "skip if either market is closed" would waste the morning pair on a US holiday (the fresh CN close is precisely its point) and waste the evening pair on a CN holiday. Each pair skips only when its own market is closed.

## Fail-open: the gate never blocks a run

The check cannot be allowed to become a new source of missed briefs. If `exchange_calendars` is missing, the calendar lookup raises, the date string is malformed, anything — the gate prints the error to stderr and returns 0, treating the day as a trading day. An extra unattended run is benign; a wrongly skipped run is a whole missing brief, the worst failure this layer can have. This is the automation-side mirror of "degradation is published, not hidden" (ADR-0004): the system prefers doing the work over trusting a broken check.

## The weekend translation gap-fill

The briefs own full-pair translation of the news dataset (ADR-0003) — every run re-translates every item, which doubles as a catch-up pass. But briefs do not run on weekends, so weekend news would sit unilingual until Monday 12:30. Rather than accept that, the news refresh gains a **weekend-only** gap-fill pass: translate only the items whose canonical bilingual pair is incomplete, write `news.zh-translations.json`, merge via `--analysis-only`. It is deliberately *not* a full pass — the briefs' full pass would re-translate the same items hours later, doubling AI cost for identical output. On weekdays the news task skips the pass entirely; the 12:30 brief covers those items the same day. Any item a gated day left untranslated is caught up by the next brief that runs, because every brief does a full pass.

## Why a calendar library instead of a hand-maintained list

No holiday infrastructure existed in the repo. A static `config/holidays.yaml` would fit the config-as-fact style (ADR-0005), but CN holidays are announced annually by the State Council and ad-hoc closures (observed days, special sessions) are easy to miss — a stale list silently stops gating. `exchange_calendars` ships XNYS and XSHG calendars that update with the package. The import is confined to `pipeline/schedule/trading_day.py`; the pipeline itself never imports it (the same blast-radius reasoning as the akshare isolation note in `pyproject.toml`).

## Consequences

- Four tasks now trigger only Monday–Friday; the news refresh stays daily. A weekend has exactly one MRD trigger: news at 04:30 Dublin.
- A holiday falling on a weekday skips the affected pair via the gate; the next trading day resumes. Briefs that do run still perform a full translation pass, so nothing waits long for a translation.
- If the calendar library is unavailable, holiday gating degrades (tasks run, warning logged); nothing else changes.
- The gate is contract-tested: `tests/pipeline/test_trading_day.py` asserts known 2026 closures (CN New Year break, CNY week, National Day week; US observed July 4, Labor Day, Christmas) and the fail-open path, verified against `exchange_calendars` 4.13.2.
- Automation names now carry the schedule ("weekdays 12:30 Dublin", "daily 04:30 Dublin") so the calendar reads off the automation list itself.
