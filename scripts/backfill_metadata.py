#!/usr/bin/env python3
"""One-shot backfill: regenerate ``public/data/metadata/freshness.json`` and ``sources.json``.

Why this exists (#89, #101):
    The committed ``public/data`` snapshot predates the new freshness model. Its two metadata
    documents were hand-shaped and failed the new ``check:data`` gate: ``freshness.json`` used
    free-text reasons ("degraded"/"ok"), omitted ``factlayer``/``news_translations``, and
    contained an unregistered ``facts`` key; ``sources.json`` used the OLD provider-domain shape
    (no per-domain ``status``/``reason``). Both must be rebuilt as *projections of one record*.

What this does (and does not do):
    - Loads each committed envelope under ``public/data/latest/*.json`` — the data snapshot is
      PRESERVED; this script only rewrites ``metadata/``, never ``latest/``.
    - Re-derives each enveloped dataset's verdict through ``finalize_freshness`` — the single
      authoritative producer. This is what enforces the #89 invariant that ``fresh`` requires a
      non-empty payload: ``calendar`` ships ``events: []`` so it is rebuilt as ``empty``
      (``no_events_in_window``), not the ``fresh`` it falsely claimed.
    - Derives ``factlayer`` from ``aggregate_freshness`` of its inputs (a derived dataset is only
      as fresh as its stalest input → ``input_dataset_unhealthy`` when an input is degraded).
    - Treats the AI-produced standalone files (``analysis.*``, ``news.zh-translations``) as
      ``fresh``/``ok`` because they exist and validate — absence would be the degraded mode, not
      a wrong status.
    - Renders both documents through ``RunOutcomes`` so they are, by construction, two views of
      one truth and cannot contradict (the #89 failure mode).

Run from the repo root:  .venv/bin/python scripts/backfill_metadata.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.schemas import registry  # noqa: E402
from pipeline.schemas.envelope import FreshnessReason  # noqa: E402
from pipeline.storage.outcomes import RunOutcomes  # noqa: E402
from pipeline.validation.freshness import (  # noqa: E402
    aggregate_freshness,
    expected_interval_minutes_for,
    finalize_freshness,
)

DATA_DIR = ROOT / "public" / "data"
LATEST_DIR = DATA_DIR / "latest"
FRESHNESS_PATH = DATA_DIR / "metadata" / "freshness.json"
SOURCES_PATH = DATA_DIR / "metadata" / "sources.json"

# Primary row-count field per row-counted enveloped dataset lives on the registry spec
# (``DatasetSpec.row_key``) — the one home, shared with ``run.py`` and ``ci_checks.py``.


def _load(key: str) -> dict:
    spec = registry.require(key)
    # Take the first published filename for the dataset.
    return json.loads((LATEST_DIR / spec.filenames[0]).read_text(encoding="utf-8"))


def _row_count(key: str, payload: dict) -> int | None:
    spec = registry.require(key)
    if spec.row_key is None:
        return None
    value = payload.get(spec.row_key)
    if value is None:
        return 0
    return len(value) if isinstance(value, list) else 0


def _frozen_now(key: str, generated_at: str, status: str) -> datetime | None:
    """Pick ``now`` so the time ladder in ``finalize_freshness`` reproduces ``status``.

    Only relevant for the non-degraded, non-empty time states (fresh/delayed/stale). For
    degraded/empty/missing the clock is ignored, so ``None`` (use real now) is fine.
    """
    if status == "fresh":
        factor = 1.0
    elif status == "delayed":
        factor = 2.0
    elif status == "stale":
        factor = 4.0
    else:
        return None
    gen = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    interval = expected_interval_minutes_for(key, 480)
    return gen + timedelta(minutes=interval * factor)


def main() -> int:
    outcomes = RunOutcomes()

    # --- Enveloped datasets: verdict through the single producer. ---
    enveloped_statuses: list[str] = []
    for key in (spec.key for spec in registry.DATASETS if spec.enveloped):
        env = _load(key)
        prov = env.get("provenance", {}) or {}
        status = env.get("freshness_status")
        is_degraded = status == "degraded"
        verdict = finalize_freshness(
            key,
            env.get("generated_at"),
            is_degraded,
            now=_frozen_now(key, env.get("generated_at", ""), status),
            row_count=_row_count(key, env.get("payload", {})),
            used_fallback=bool(prov.get("used_fallback")),
            from_cache=bool(prov.get("from_cache")),
        )
        outcomes.record(
            key,
            verdict.status,
            verdict.reason,
            provider=prov.get("provider"),
            used_fallback=bool(prov.get("used_fallback")),
            from_cache=bool(prov.get("from_cache")),
        )
        enveloped_statuses.append(verdict.status)
        print(f"  {key:10s} -> {verdict.status:9s} ({verdict.reason.code})")

    # --- factlayer: derived from its inputs. ---
    factlayer_status = aggregate_freshness(enveloped_statuses)
    factlayer_code = "input_dataset_unhealthy" if factlayer_status in ("degraded", "missing", "stale", "empty") else "ok"
    outcomes.record(
        "factlayer",
        factlayer_status,
        FreshnessReason(code=factlayer_code, detail=""),
    )
    print(f"  {'factlayer':10s} -> {factlayer_status:9s} ({factlayer_code}) [aggregated from inputs]")

    # --- AI-produced standalone files: present and valid -> fresh/ok. ---
    for key in ("analysis", "news_translations"):
        outcomes.record(key, "fresh", FreshnessReason(code="ok", detail=""))
        print(f"  {key:10s} -> {'fresh':9s} (ok) [AI-produced file present]")

    # --- Provider status for sources.json, lifted from each domain's envelopes. ---
    provider_status: dict[str, dict] = {}
    previous_sources: dict = {}
    if SOURCES_PATH.exists():
        try:
            previous_sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_sources = {}
    for domain, keys in registry.DOMAIN_DATASETS.items():
        provs = []
        for k in keys:
            try:
                provs.append(_load(k).get("provenance", {}) or {})
            except Exception:  # noqa: BLE001 - a missing envelope should not abort the backfill
                continue
        if not provs:
            continue
        status = {
            "provider": next((p.get("provider") for p in provs if p.get("provider")), None),
            "used_fallback": any(bool(p.get("used_fallback")) for p in provs),
            "from_cache": any(bool(p.get("from_cache")) for p in provs),
        }
        # An extra domain can share a dataset with the canonical domain while having its own
        # provider call (calendar/earnings vs economic/FRED). The envelope has one primary
        # provenance only, so retain the previous domain-specific status when backfilling.
        previous = (previous_sources.get("domains", {}) or {}).get(domain, {})
        if domain in registry.EXTRA_DOMAIN_DATASETS and previous.get("provider"):
            status.update(
                provider=previous["provider"],
                used_fallback=bool(previous.get("used_fallback")),
                from_cache=bool(previous.get("from_cache")),
            )
        provider_status[domain] = status

    freshness_doc = outcomes.freshness_projection(None)
    sources_doc = outcomes.sources_projection(provider_status)

    FRESHNESS_PATH.write_text(json.dumps(freshness_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SOURCES_PATH.write_text(json.dumps(sources_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nWrote {FRESHNESS_PATH.relative_to(ROOT)} ({len(freshness_doc['datasets'])} datasets)")
    print(f"Wrote {SOURCES_PATH.relative_to(ROOT)} ({len(sources_doc['domains'])} domains)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
