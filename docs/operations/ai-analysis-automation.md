# WorkBuddy AI Automation Integration Manual

**Applies to:** WorkBuddy scheduled automation (deepseek v4 flash) generating bilingual AI briefs outside the pipeline.
**Contract:** input/output are both disk files (architecture §1.5); the pipeline stays deterministic and replayable; AI is a "pluggable external step".

---

## 1. Daily cadence (frozen)

| Session | ET window (frozen) | Automation time (Dublin local) | Trigger condition |
|---|---|---|---|
| Pre-market | 07:30 ET | 12:30 | After the pipeline pre-market refresh (11:30) |
| Post-market | 16:30 ET | 21:30 | After the pipeline post-market refresh (20:30) |

2 runs per day. When quota is exhausted or a run fails, skip this step and mark `degraded` (see §5 drill).

> Timezone note: automation rrule times are **machine-local (Dublin, GMT+1)** — 12:30 Dublin = 07:30 ET, 21:30 Dublin = 16:30 ET, year-round (modulo US/EU DST transition weeks). Each AI brief runs 1h after the corresponding data refresh (11:30 / 20:30 Dublin), so it always reads the freshest facts.json.

## 2. Input / output contract

**Input (pipeline output, deterministic):**

| File | Description |
|---|---|
| `public/data/latest/facts.json` | Fact layer: risk results + macro/market summary + Top news + next-7-day events + `evidence_index` |
| `public/data/latest/news.json` | News (canonical English headline/summary + `lang` en\|zh for translation routing, ADR-0003) |

**Output (AI output, validated):**

| File | Description |
|---|---|
| `public/data/latest/analysis.zh-CN.json` | Chinese brief (AnalysisDataset schema) |
| `public/data/latest/analysis.en.json` | English brief (AnalysisDataset schema) |
| `public/data/latest/news.zh-translations.json` | News bilingual translations, symmetric full pair — `{id, title, summary, title_zh, summary_zh}`, every item, both directions (ADR-0003) |

**Tools (in repo, called in order by the automation):**

```bash
# 1) Fact layer → bilingual copy prompt
python -m pipeline.analysis.build_prompt --lang zh-CN    # Chinese prompt
python -m pipeline.analysis.build_prompt --lang en       # English prompt

# 2) Output validation (schema + evidence_refs + bilingual consistency)
python -m pipeline.analysis.validate \
  --zh public/data/latest/analysis.zh-CN.json \
  --en public/data/latest/analysis.en.json \
  --facts public/data/latest/facts.json

# 3) Freshness check (for the automation to decide whether to skip)
python -m pipeline.analysis.freshness --dataset facts
```

## 3. Automation steps (WorkBuddy trigger)

1. `git pull --rebase origin dev` (pull latest facts.json).
2. Check `facts.json` freshness (`pipeline.analysis.freshness`): stale is still acceptable, but the output carries a `data_freshness` annotation.
3. `build_prompt.py` produces prompts (once for zh-CN, once for en, including evidence-index snippets): `python -m pipeline.analysis.build_prompt --lang zh-CN` / `--lang en`.
4. Call deepseek v4 flash to generate three outputs (Chinese brief / English brief / news bilingual translations).
5. Write the three output files: `analysis.zh-CN.json` / `analysis.en.json` / `news.zh-translations.json` — the translations are a **symmetric full pair for every item** in `news.json` (ADR-0003 canonical bilingual, not a top-N sample), as `NewsTranslationsDataset { items: [{id, title, summary, title_zh, summary_zh}], updated_at }`:
   - `lang == "en"` items: `title`/`summary` = the item's English verbatim; `title_zh`/`summary_zh` = your Chinese translation.
   - `lang == "zh"` items: `title`/`summary` = your English translation; `title_zh`/`summary_zh` = the item's Chinese verbatim.
   - **Graceful fallback:** if a translation genuinely cannot be produced for an item, omit that id from the list (the merge leaves it unchanged); never emit an empty-string or placeholder record. The schema accepts partial records, so a missing translation degrades to the other language in the UI.
   Covering every item each run doubles as the catch-up pass for already-stored data (the merge is keyed by `id`; the English side applies only to `lang == "zh"` items, so canonical English is never rewritten).
6. Validate with the CLI (`--zh/--en/--facts`, no `--locale`):
   - Schema is valid (no implicit fields / NaN / invalid enums / invalid time)
   - Every `evidence_refs` is findable in `evidence_index`
   - **Bilingual consistency**: `market_state` / `market_regime` / `confidence` / the `evidence_refs` set / all numbers in the text must be exactly identical; only the expression language may differ
   - On failure, retry ≤2 times (regenerate or patch locally).
7. Publish linkage: after validation passes, run `python -m pipeline.run --analysis-only` — it flips `metadata/freshness.json` `analysis` to `fresh`, merges `news.zh-translations.json` into `news.json` when present (and records `missing` in `metadata/translations.json` when the translations step was skipped), keeping a single source of truth.
8. `git commit + push (dev)` (`AI:`-prefixed message) → trigger Pages build.

**Bilingual consistency rule (architecture §3.4):** inconsistency → refuse to publish; rather skip this run than publish a wrong conclusion.

## 4. Validation failure / quota-exhausted degradation drill

**Scenario A: validation fails and retries are exhausted**

1. Do not write any analysis files, do not push.
2. Keep the last successfully published analysis files (the frontend keeps showing the old brief + stale marker).
3. On the next pipeline run, mark the analysis dataset `degraded` in `metadata/freshness.json` (reason `analysis_failed`).
4. The frontend AI block shows degraded instead of missing.

**Scenario B: quota exhausted**

1. Skip the generation step (do not call the LLM).
2. Same as above: do not push analysis files, mark `degraded`.
3. After quota is restored, the next scheduled time recovers automatically; you can also manually trigger one post-market automation run.

**Drill check list:**

- [ ] `git status` has no leftover unpushed analysis files
- [ ] the `analysis` dataset is `degraded` in `metadata/freshness.json`
- [ ] the frontend AI block shows "partially degraded" instead of crashing/blank
- [ ] `scripts/validate_data.sh` still passes (missing AI is a WARNING, not an ERROR)

## 5. Manual drill steps (verify the whole chain)

```bash
cd /path/to/market-risk-dashboard
git pull --rebase origin dev

# 1) Confirm the fact layer is fresh
.venv/bin/python -m pipeline.analysis.freshness --dataset facts

# 2) Generate prompts (confirm the template works)
.venv/bin/python -m pipeline.analysis.build_prompt --lang zh-CN > /tmp/prompt-zh.txt
.venv/bin/python -m pipeline.analysis.build_prompt --lang en    > /tmp/prompt-en.txt

# 3) Generate with deepseek v4 flash following the prompts (done inside WorkBuddy automation)
#    Write output to public/data/latest/analysis.zh-CN.json / analysis.en.json / news.zh-translations.json

# 4) Validate
.venv/bin/python -m pipeline.analysis.validate \
  --zh public/data/latest/analysis.zh-CN.json \
  --en public/data/latest/analysis.en.json \
  --facts public/data/latest/facts.json

# 5) Full data validation (T05 gate)
scripts/validate_data.sh

# 6) Commit and push
git add public/data/latest/analysis.zh-CN.json public/data/latest/analysis.en.json public/data/latest/news.zh-translations.json
git commit -m "ai: bilingual brief $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin dev
```

## 6. Troubleshooting

| Symptom | Cause | Handling |
|---|---|---|
| validate reports schema error | AI output missing fields / invalid enum | Cross-check against the output schema field list; retry generation |
| validate reports evidence_ref not found | AI referenced evidence outside `evidence_index` | Only reference evidence snippets provided in the prompt; regenerate |
| Bilingual number mismatch | zh/en texts have different numbers (e.g. 3.2 vs 3.20) | Keep the original values identical; retry |
| Quota exhausted | deepseek quota used up | Skip + degraded (see §4) |
| facts stale for a long time | pipeline has not run | Run the pipeline first (`docs/operations/scheduled-task.md`) |

## 7. Maintenance notes

- Changing model / automation platform **does not touch the pipeline**: only change the calls in steps 3-4 of this manual.
- The news translation file is merged into `news.json` by step 7's `--analysis-only` in the same run (`pipeline/collectors/news.py` merge step + `pipeline/run.py`), keeping a single source of truth; the automation **must not** directly modify `news.json`.
- **Catch-up (backfill) pass:** because the translation step covers every item in `news.json` each run and the merge is keyed by `id`, the next scheduled brief backfills the live file automatically. There are no news history slices (`public/data/history/` holds market/risk only), so no per-slice translation pass exists; the live file is the only news dataset.
- Terminology follows `docs/glossary.md`; the prompt template `pipeline/analysis/build_prompt.py` already embeds the key term mapping.
