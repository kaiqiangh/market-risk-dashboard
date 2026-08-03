# Market Risk Dashboard

**Global Market Risk Intelligence Dashboard** — a cross-asset, bilingual (zh-CN / en) market risk
intelligence board for personal investment research. Static-first: a local data pipeline produces
deterministic JSON facts, an optional AI step generates bilingual briefs, and GitHub Pages serves
the result.

> ⚠️ Risk scores are a **modeled estimate of market stress**, not an exact crash probability, and do
> not constitute investment advice.

## Architecture

See `docs/architecture.md` (internal). High-level data flow:

```
Local pipeline (Scheduled Task) → facts.json (deterministic)
  → AI analysis (WorkBuddy automation, optional) → analysis.zh-CN/en.json
  → git push (dev) → GitHub Actions (build + deploy only) → GitHub Pages
```

Schema triplicate: JSON Schema (data files) + Zod (frontend runtime) + Pydantic (pipeline runtime) —
same semantics, three implementations; any validation failure blocks publication.

## Quick start

### Frontend

```bash
npm install
npm run dev        # local dev server (http://localhost:5173)
npm run build      # production build → dist/
npm test           # vitest (Zod contract tests)
```

### Pipeline

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pipeline.run --dry-run   # skeleton: config self-check + plan, no-op exit 0
python -m pytest tests/pipeline/ -v
```

Copy `.env.example` to `.env` and fill in API keys (local only, gitignored).

## Repository layout

```
config/            pipeline runtime config (universe / risk model / sources / news)
pipeline/          data pipeline (schemas, analysis contract, providers, collectors…)
public/data/       static data consumed by the frontend (produced by pipeline + AI)
src/               React frontend (pages, components, charts, i18n, lib)
tests/             fixtures + pipeline/frontend/i18n tests
.github/workflows/ build+deploy only (no data collection, no secrets)
```

## Milestones

- **T01** Project infrastructure (this skeleton)
- **T02** Data contract layer (Pydantic + Zod + AI contract + fixtures)
- **T03** Data pipeline (providers → indicators → 6-dimension risk → facts layer → storage)
- **T04** Frontend UI (8 pages, i18n, themes, charts)
- **T05** Integration, validation, calibration report, deployment

## License

MIT — see [LICENSE](LICENSE).
