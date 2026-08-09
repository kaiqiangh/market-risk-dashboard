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

**WorkBuddy automation mapping (currently the actual scheduler):** the four MRD automations are scheduled in machine-local time (Dublin, GMT+1) — data refresh `--full` at 11:30 + 20:30 Dublin (≈ 06:30 / 15:30 ET), overnight `--news-only` at 04:30 Dublin (≈ 23:30 ET), and the AI briefs at 12:30 + 21:30 Dublin (≈ 07:30 / 16:30 ET) 1h after each refresh. The ET windows hold year-round (modulo US/EU DST transition weeks). If you switch to a local scheduler (cron/launchd), prefer ET-anchored times.

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

## 3. Standard flow (git pull → run → full validation → commit → push)

Each task execution script (`scripts/run_scheduled.sh`, see example at the end) should include:

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if ! .venv/bin/python -c "import pydantic, yaml, pydantic_settings" >/dev/null 2>&1; then
  echo "Validation capability unavailable"
  exit 10
fi

# 0) Environment prep — failure is fatal; never collect from unconfirmed local state
git pull --rebase origin dev

# 1) Run the pipeline
.venv/bin/python -m pipeline.run --full || { echo "Pipeline failed, see artifacts/logs/"; exit 21; }

# 2) Full data validation, contract drift, and mandatory secret scan (T05 gate)
if scripts/validate_data.sh --scheduled; then
  :
else
  VALIDATION_STATUS=$?
  if [[ "$VALIDATION_STATUS" -eq 10 ]]; then
    echo "Validation capability unavailable, not committing"
    exit 10
  fi
  echo "Full validation failed, not committing"
  exit 22
fi

# 3) Substantive-change check + commit (avoid meaningless Actions triggers, architecture §8.14)
if git diff --quiet public/ config/; then
  echo "No substantive changes, skipping commit"
  exit 0
fi
git add public/ config/
git commit -m "data: scheduled update $(date -u +%Y-%m-%dT%H:%M:%SZ)" || { echo "Commit failed, not pushing"; exit 23; }
COMMIT_SHA="$(git rev-parse HEAD)"
git show --quiet "$COMMIT_SHA"
git push origin dev || { echo "Push failed; retry verified local commit $COMMIT_SHA"; exit 24; }
REMOTE_SHA="$(git ls-remote origin refs/heads/dev | awk '{print $1}')"
[[ "$REMOTE_SHA" == "$COMMIT_SHA" ]] || { echo "Remote verification failed for $COMMIT_SHA"; exit 24; }
```

The default validation path requires the project Python environment and full Pydantic
validation. A missing dependency or Node runtime for the mandatory secret scan is an error.
Developers may run `scripts/validate_data.sh --diagnostic-reduced` for an explicitly marked
Node-only structural check, but that mode is not accepted by scheduled or production paths.

### Schema-change PRs: the expected-red window (#74)

`validate-data.yml` watches `pipeline/schemas/**` (plus `pipeline/validation/**`,
`public/data/**`, `scripts/validate_data.sh`, `scripts/validate-json.mjs`,
`config/sources.yaml`). When a PR changes a schema, the committed `public/data` does not
yet match the new contract, so the data gate turns **red** — and it must **stay red**
until the next scheduled run regenerates and pushes `public/data` (usually within hours).

A red run on a schema-change PR is the system working, not a mistake:

- The failure text names the contract mismatch (Pydantic/Zod validation), not something incidental.
- Do **not** "fix" the red by adding `continue-on-error`, a skip label, or an `if:` escape
  on the gate. A green gate during the window would be a lie, and this release is about
  honest data.
- The window closes by itself: run the scheduled task (or `scripts/run_scheduled.sh --full`)
  to regenerate and validate `public/data`, and
  the same PR turns green.

## 4. Offline / failure degradation behavior

| Scenario | Pipeline behavior | Operations action |
|---|---|---|
| A Provider fails | Go down the fallback chain (backup → last-good cache → `degraded`), **does not abort the whole pipeline** | No intervention needed; check `metadata/sources.json` |
| All market sources fail | Keep the most recent valid data + mark `freshness=missing/stale` | Check network/proxy; manually retry with `--market-only` if needed |
| Local machine offline | Pipeline exits with error, no new data | Automatically retried at next scheduled time; no manual action |
| git pull/rebase fails | Collection does not start | Fix repository/network state, then retry the scheduled task |
| Full validation or secret scan fails | No commit is created | Fix the reported data/capability issue, then rerun validation and the task |
| git commit fails | No push is attempted | Inspect the local repository and retry after fixing the commit error |
| git push or remote verification fails | Verified commit remains local but unpublished | Retry push for the reported commit hash after repository/network recovery |
| AI brief missing | Analysis dataset `freshness=degraded`, frontend AI block degrades | Drill per `docs/operations/ai-analysis-automation.md` |

**Principle (architecture §1.1/#8):** provider exceptions use graceful multi-source degradation and
must remain visible in run reports. Validation and repository-state failures are different: they
stop publication and must never be converted into a successful scheduled run.

## 5. .env secret management

- `.env` is gitignored (contains `DATA_FRED_API_KEY` / `DATA_COINGECKO_API_KEY` / `DATA_FMP_API_KEY`).
- **Secrets stay on this machine only**, never commit them; the frontend/CI must not contain keys (architecture §8.13/PRD §24).
- Rotation: after modifying `.env`, restart the next task; no code change needed.
- Backup: secrets can be stored in a password manager; copy `.env` to the new machine when migrating (keep gitignore unchanged).
- The pipeline still runs without keys: the corresponding FRED/CoinGecko/FMP providers degrade/skip, other data proceeds normally.

## 6. Recovery & troubleshooting

1. View the latest run report: `ls -t artifacts/logs/run-report-*.json | head -1`
2. Check Provider health: `cat public/data/metadata/sources.json`
3. Manual retry: `scripts/run_scheduled.sh --full`
4. Fix stale data: confirm local time/timezone is correct (scheduling follows ET, writes use UTC ISO 8601).
5. Windows Task Scheduler: set the trigger to "weekdays 07:30/16:30/23:30", action `cmd /c scripts\run_scheduled.bat`.
6. macOS: use a launchd plist or `crontab`, redirect logs to `artifacts/logs/cron.log`.

## 7. Example script

A full example is in the repo at `scripts/run_scheduled.sh` (can be copied and referenced by the task scheduler).
