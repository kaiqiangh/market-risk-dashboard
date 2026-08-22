#!/usr/bin/env python3
"""One-shot backfill: regenerate metadata/freshness.json and metadata/sources.json.

Why this exists (#89, #101):
    The committed public/data snapshot predates the new freshness model; both metadata
    documents were hand-shaped and failed check:data. They must be rebuilt as projections
    of one record (RunOutcomes), which is what this script does.

What this does (and does not do):
    - Loads each committed envelope under <data-dir>/latest/*.json - the data snapshot is
      PRESERVED; this script only rewrites metadata, never latest/.
    - Re-derives each enveloped verdict through finalize_freshness - the single
      authoritative producer (#89 invariant: fresh requires a non-empty payload).
    - Derives factlayer from aggregate_freshness of its inputs.
    - Treats AI-produced standalone files (analysis.*, news_translations) honestly (#188):
      absent -> missing; present but schema-invalid -> degraded/provider_parse_error;
      present and valid -> fresh/ok. The old behavior recorded fresh on existence alone -
      exactly the dishonesty #89 removed.
    - Writes both documents through StorageWriter's atomic path (#188): a repair tool must
      never leave the files it repairs truncated after a mid-write crash.

Failure semantics (#188): an unreadable or non-object latest/*.json is skipped with a named
stderr note (consistent with the provider loop) and the script exits 1 - silently partial
metadata from a repair tool would be a trap.

Run from the repo root:  .venv/bin/python scripts/backfill_metadata.py [--data-dir public/data]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.metadata import row_count_for  # noqa: E402
from pipeline.schemas import registry  # noqa: E402
from pipeline.schemas.envelope import FreshnessReason  # noqa: E402
from pipeline.storage.outcomes import RunOutcomes  # noqa: E402
from pipeline.storage.writer import StorageWriter  # noqa: E402
from pipeline.validation.freshness import (  # noqa: E402
    REPRESENTATIVE_BAND_FACTOR,
    aggregate_freshness,
    expected_interval_minutes_for,
    finalize_freshness,
)


def _load(path: Path, key: str) -> dict | None:
    """Read one published document, or None with a NAMED stderr note (#188).

    The old unguarded version crashed the whole backfill on the first corrupt file while
    the provider loop right below deliberately skipped - two failure philosophies in one
    script. Skip-and-report everywhere; the exit code carries the failure.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  [skip] {key}: unreadable {path.name}: {exc}", file=sys.stderr)
        return None
    if not isinstance(value, dict):
        print(f"  [skip] {key}: {path.name} is not a JSON object", file=sys.stderr)
        return None
    return value


def _frozen_now(key: str, generated_at: str, status: str) -> datetime | None:
    """Pick now so the time ladder in finalize_freshness reproduces status.

    Only relevant for the time states (fresh/delayed/stale); for degraded/empty/missing
    the clock is ignored, so None (use real now) is fine. Band factors come from
    validation.freshness (single source, #188); an unparseable generated_at returns None
    instead of crashing the backfill.
    """
    factor = REPRESENTATIVE_BAND_FACTOR.get(status)
    if factor is None:
        return None
    try:
        gen = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        print(f"  [warn] {key}: unparseable generated_at; using real now", file=sys.stderr)
        return None
    interval = expected_interval_minutes_for(key, 480)
    return gen + timedelta(minutes=interval * factor)


def _record_ai_documents(outcomes: RunOutcomes, latest_dir: Path) -> None:
    """Record the AI-produced standalone files with schema-verified honesty (#188).

    The old docstring claimed "present and validate" while the code only checked
    existence. Now every registered filename must exist AND validate through the
    spec's own model before the dataset may be recorded fresh.
    """
    for key in ("analysis", "news_translations"):
        spec = registry.require(key)
        failure: str | None = None
        for filename in spec.filenames:
            path = latest_dir / filename
            if not path.exists():
                failure = "missing " + filename
                break
            loaded = _load(path, key)
            if loaded is None:
                failure = "unreadable " + filename
                break
            try:
                spec.model.model_validate(loaded)
            except Exception as exc:  # noqa: BLE001 - any invalid document is one degraded dataset
                failure = "invalid " + filename + ": " + type(exc).__name__
                break
        if failure is None:
            outcomes.record(key, "fresh", FreshnessReason(code="ok", detail="AI documents present and schema-valid"))
            state = "fresh"
            note = "(ok) [AI documents validated]"
        elif failure.startswith("missing"):
            outcomes.record(key, "missing", FreshnessReason(code="not_collected_this_run", detail=failure))
            state = "missing"
            note = "(" + failure + ")"
        else:
            outcomes.record(key, "degraded", FreshnessReason(code="provider_parse_error", detail=failure))
            state = "degraded"
            note = "(" + failure + ")"
        print("  " + key.ljust(10) + " -> " + state.ljust(9) + " " + note)


def _display(path: Path) -> str:
    """Path as repo-relative when it lives under ROOT, else absolute (#188: --data-dir)."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild freshness.json and sources.json from committed envelopes")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "public" / "data")
    args = parser.parse_args(argv)
    data_dir = args.data_dir
    latest_dir = data_dir / "latest"

    outcomes = RunOutcomes()
    writer = StorageWriter(data_dir)
    skipped = 0

    # --- Enveloped datasets: verdict through the single producer. ---
    enveloped_statuses: list[str] = []
    for key in (spec.key for spec in registry.DATASETS if spec.enveloped):
        spec = registry.require(key)
        env = _load(latest_dir / spec.filenames[0], key)
        if env is None:
            skipped += 1
            continue
        prov = env.get("provenance", {}) or {}
        status = env.get("freshness_status") or ""
        verdict = finalize_freshness(
            key,
            env.get("generated_at"),
            status == "degraded",
            now=_frozen_now(key, env.get("generated_at", "") or "", status),
            row_count=row_count_for(key, env.get("payload", {})),
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
        print("  " + key.ljust(10) + " -> " + verdict.status.ljust(9) + " (" + verdict.reason.code + ")")

    # --- factlayer: derived from its inputs. ---
    factlayer_status = aggregate_freshness(enveloped_statuses) if enveloped_statuses else "missing"
    if factlayer_status in ("degraded", "missing", "stale", "empty"):
        factlayer_code = "input_dataset_unhealthy"
    else:
        factlayer_code = "ok"
    outcomes.record("factlayer", factlayer_status, FreshnessReason(code=factlayer_code, detail=""))
    print("  factlayer   -> " + factlayer_status.ljust(9) + " (" + factlayer_code + ") [aggregated from inputs]")

    # --- AI-produced standalone files: present AND schema-valid -> fresh/ok (#188). ---
    _record_ai_documents(outcomes, latest_dir)

    # --- Provider status for sources.json, lifted from each domain's envelopes. ---
    provider_status: dict[str, dict] = {}
    previous_sources: dict = {}
    sources_path = data_dir / "metadata" / "sources.json"
    if sources_path.exists():
        try:
            previous_sources = json.loads(sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_sources = {}
    for domain, keys in registry.DOMAIN_DATASETS.items():
        provs = []
        for k in keys:
            kspec = registry.require(k)
            loaded = _load(latest_dir / kspec.filenames[0], k)
            if loaded is not None:
                provs.append(loaded.get("provenance", {}) or {})
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

    # Atomic, same-filesystem writes (#188): a repair tool must not leave truncated metadata.
    freshness_path = data_dir / "metadata" / "freshness.json"
    writer.write_json(freshness_path, freshness_doc)
    writer.write_json(data_dir / "metadata" / "sources.json", sources_doc)

    freshness_rel = _display(freshness_path)
    sources_rel = _display(data_dir / "metadata" / "sources.json")
    n_datasets = len(freshness_doc["datasets"])
    n_domains = len(sources_doc["domains"])
    print("")
    print(f"Wrote {freshness_rel} ({n_datasets} datasets)")
    print(f"Wrote {sources_rel} ({n_domains} domains)")
    if skipped:
        print(f"[backfill_metadata] {skipped} dataset(s) skipped; metadata is PARTIAL", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())