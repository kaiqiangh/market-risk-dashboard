# WorkBuddy AI Automation Integration Manual

**Applies to:** WorkBuddy scheduled automation (deepseek v4 flash) generating bilingual AI briefs outside the pipeline.
**Contract:** input/output are both disk files (architecture §1.5); the pipeline stays deterministic and replayable; AI is a "pluggable external step".

---

## 1. Daily cadence (frozen)

| Session | ET time | Trigger condition |
|---|---|---|
| Pre-market | 07:30 ET | After the pipeline pre-market run (facts.json updated) |
| Post-market | 16:30 ET | After the pipeline post-market run |

2 runs per day. When quota is exhausted or a run fails, skip this step and mark `degraded` (see §5 drill).

## 2. Input / output contract

**Input (pipeline output, deterministic):**

| File | Description |
|---|---|
| `public/data/latest/facts.json` | Fact layer: risk results + macro/market summary + Top news + next-7-day events + `evidence_index` |
| `public/data/latest/news.json` | News (including original English headlines) |

**Output (AI output, validated):**

| File | Description |
|---|---|
| `public/data/latest/analysis.zh-CN.json` | Chinese brief (AnalysisDataset schema) |
| `public/data/latest/analysis.en.json` | English brief (AnalysisDataset schema) |
| `public/data/latest/news.zh-translations.json` | English news Chinese translations (title_zh/summary_zh) |

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
3. `build_prompt.py` produces prompts (once for zh-CN, once for en, including evidence-index snippets).
4. Call deepseek v4 flash to generate three outputs (Chinese brief / English brief / news Chinese translation).
5. `pipeline.analysis.validate` validates:
   - Schema is valid (no implicit fields / NaN / invalid enums / invalid time)
   - Every `evidence_refs` is findable in `evidence_index`
   - **Bilingual consistency**: `market_state` / `market_regime` / `confidence` / the `evidence_refs` set / all numbers in the text must be exactly identical; only the expression language may differ
   - On failure, retry ≤2 times (regenerate or patch locally).
6. Write the three output files → `git commit + push (dev)` → trigger Pages build.

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
- The news translation file is merged into `news.json` by the next pipeline run (`pipeline/collectors/news.py` merge step), keeping a single source of truth; the automation **must not** directly modify `news.json`.
- Terminology follows `docs/glossary.md`; the prompt template `pipeline/analysis/build_prompt.py` already embeds the key term mapping.
