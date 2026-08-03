# Local Scheduled Task Operations Manual

**Applies to:** scheduled local tasks of the data pipeline (Windows Task Scheduler / macOS launchd / cron).
**Goal:** automatically collect → compute → validate → push 2-3 times per day to keep `public/data` fresh and drive GitHub Pages auto-deployment.

---

## 1. Run cadence

Scheduled on US equity trading days (ET), 2-3 times per day; on non-trading days (weekends/US market holidays) market data collection may be skipped, while news collection can be kept.

| Session | ET time | Command | Purpose |
|---|---|---|---|
| Pre-market | 07:30 ET | `python -m pipeline.run --full` | Overnight macro/news + pre-market state snapshot |
| Post-market | 16:30 ET | `python -m pipeline.run --full` | Same-day closing market data + risk model update |
| Overnight (optional) | 23:30 ET | `python -m pipeline.run --news-only` or `--full` | Asia-session news / overnight market data supplement |

**ET ↔ local time mapping:** convert to your local timezone in `.env` or the task schedule (example: ET 07:30 = UTC 11:30 (DST) / 12:30 (standard time), Beijing 19:30/20:30 same day).

**WorkBuddy automation mapping (currently the actual scheduler):** the four MRD automations implement this cadence at **fixed UTC times** — data refresh `--full` at 11:30 + 20:30 UTC (pre/post-market), overnight `--news-only` at 03:30 UTC, and the AI briefs at 12:30 + 21:30 UTC right after each refresh. These match the ET windows above during US standard time; during DST the ET equivalent shifts ~1h later (e.g. 12:30 UTC = 08:30 ET in summer). If you switch to a local scheduler (cron/launchd), prefer ET-anchored times so the windows stay fixed year-round.

> Note: expected market/news update frequency is 2-3 times/day (architecture §8.5); FRED macro data follows a T+1 release cadence; `freshness` determination is described in `pipeline/validation/freshness.py`.

## 2. CLI command set (frozen)

```bash
cd /path/to/market-risk-dashboard

# Full run (default): collect + indicators + 6-dimension risk + fact layer + validation + persist
python -m pipeline.run --full

# Per-domain
python -m pipeline.run --market-only     # market data + crypto + A-shares
python -m pipeline.run --macro-only      # FRED + FedWatch
python -m pipeline.run --news-only       # RSS news
python -m pipeline.run --fact-layer      # rebuild fact layer only (no collection)
python -m pipeline.run --analysis-only   # validate AI briefs + update analysis freshness + merge news translations

# Other
python -m pipeline.run --dry-run         # dry run, no writes
python -m pipeline.run --backfill        # backfill 30-90 days of history
```

It is recommended to use the project venv: `.venv/bin/python -m pipeline.run --full`.

## 3. Standard flow (git pull → run → commit → push)

Each task execution script (`scripts/run_scheduled.sh`, see example at the end) should include:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 0) Environment prep
git pull --rebase origin dev          # Pull latest (incl. AI brief, other contributors' commits)

# 1) Run the pipeline
.venv/bin/python -m pipeline.run --full || { echo "Pipeline failed, see artifacts/logs/"; exit 1; }

# 2) Data validation (T05 gate)
scripts/validate_data.sh || { echo "Data validation failed, not committing"; exit 1; }

# 3) Substantive-change check + commit (avoid meaningless Actions triggers, architecture §8.14)
if git diff --quiet public/ config/ metadata/; then
  echo "No substantive changes, skipping commit"
  exit 0
fi
git add public/ config/
git commit -m "data: scheduled update $(date -u +%Y-%m-%dT%H:%M:%SZ)" || exit 0
git push origin dev
```

## 4. Offline / failure degradation behavior

| Scenario | Pipeline behavior | Operations action |
|---|---|---|
| A Provider fails | Go down the fallback chain (backup → last-good cache → `degraded`), **does not abort the whole pipeline** | No intervention needed; check `metadata/sources.json` |
| All market sources fail | Keep the most recent valid data + mark `freshness=missing/stale` | Check network/proxy; manually retry with `--market-only` if needed |
| Local machine offline | Pipeline exits with error, no new data | Automatically retried at next scheduled time; no manual action |
| git push fails (network/conflict) | Data already written locally but not pushed | `git pull --rebase` then re-push; the frontend shows stale if data is outdated |
| AI brief missing | Analysis dataset `freshness=degraded`, frontend AI block degrades | Drill per `docs/operations/ai-analysis-automation.md` |

**Principle (architecture §1.1/#8):** a pipeline exception **must not abort the whole pipeline**; multi-source degradation is the default path, not the exception path; any failure must not produce silent errors (write `artifacts/logs/run-report-*.json`).

## 5. .env secret management

- `.env` is gitignored (contains `DATA_FRED_API_KEY` / `DATA_COINGECKO_API_KEY` / `DATA_FMP_API_KEY`).
- **Secrets stay on this machine only**, never commit them; the frontend/CI must not contain keys (architecture §8.13/PRD §24).
- Rotation: after modifying `.env`, restart the next task; no code change needed.
- Backup: secrets can be stored in a password manager; copy `.env` to the new machine when migrating (keep gitignore unchanged).
- The pipeline still runs without keys: the corresponding FRED/CoinGecko/FMP providers degrade/skip, other data proceeds normally.

## 6. Recovery & troubleshooting

1. View the latest run report: `ls -t artifacts/logs/run-report-*.json | head -1`
2. Check Provider health: `cat public/data/metadata/sources.json`
3. Manual retry: `scripts/validate_data.sh && python -m pipeline.run --full`
4. Fix stale data: confirm local time/timezone is correct (scheduling follows ET, writes use UTC ISO 8601).
5. Windows Task Scheduler: set the trigger to "weekdays 07:30/16:30/23:30", action `cmd /c scripts\run_scheduled.bat`.
6. macOS: use a launchd plist or `crontab`, redirect logs to `artifacts/logs/cron.log`.

## 7. Example script

A full example is in the repo at `scripts/run_scheduled.sh` (can be copied and referenced by the task scheduler).
