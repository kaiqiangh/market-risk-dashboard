"""Macro history: per-series archive + per-group UI bundles + manifest (#96, shape per #84 §3).

Two layers, two consumers:

- **Archive** — `history/macro/{series}/daily.json`, append-only full retention, written
  via the existing ``write_slices`` (per-series directory is mandatory: the flat
  ``history/macro`` convention would let 26 of 27 series overwrite each other, #84 §3).
  This is the only durable store for the ICE BofA series, whose FRED feed is licensed to
  a rolling 3-year window — re-fetching can never rebuild 5y, so every day stored counts.
- **Bundles** — `history/macro/{group}.{30d,90d}.json`, sparse column-oriented
  ``{series: {"d": [...], "v": [...]}}`` so mixed-frequency groups (liquidity is daily +
  weekly) need no null padding; plus `history/macro/index.json` carrying per-series
  group/frequency/unit/scale/last_observation/next_expected_release — the freshness
  surface of #84 §5.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pipeline.collectors.macro import FREQ_SPEC
from pipeline.providers.fred import DEFAULT_SERIES_META, SERIES_CATALOG

SLICES = ("30d", "90d")


def build_bundle(rows_by_series: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, list]]:
    """Sparse column-oriented bundle for one group: ``{series: {"d": [...], "v": [...]}}``."""
    bundle: dict[str, dict[str, list]] = {}
    for series, rows in rows_by_series.items():
        bundle[series] = {
            "d": [r["date"] for r in rows],
            "v": [r["value"] for r in rows],
        }
    return bundle


def build_manifest(rows_by_series: dict[str, list[dict[str, Any]]], groups: dict[str, list[str]]) -> dict[str, Any]:
    """Per-series metadata: group, frequency, unit, scale, last observation, next release."""
    manifest: dict[str, Any] = {"series": {}}
    group_of = _group_of_series(groups)
    for series, rows in rows_by_series.items():
        if series not in group_of:
            continue  # internal anchor (EFFR) — not a published series
        meta = SERIES_CATALOG.get(series, {**DEFAULT_SERIES_META, "label": series})
        last_date = rows[-1]["date"] if rows else None
        # next_expected_release is a frequency estimate (calendar estimate, not the true
        # release schedule — the full release-calendar model is #84 §5 future work).
        next_expected = None
        if last_date:
            try:
                next_expected = (
                    date.fromisoformat(last_date)
                    + timedelta(days=FREQ_SPEC.get(meta.get("frequency", "daily"), FREQ_SPEC["daily"])["next_days"])
                ).isoformat()
            except ValueError:
                next_expected = None
        manifest["series"][series] = {
            "group": group_of.get(series),
            "label": meta.get("label", series),
            "frequency": meta.get("frequency", "daily"),
            "unit": meta.get("unit", "level"),
            "scale": meta.get("scale", "level"),
            "last_observation": last_date,
            "next_expected_release": next_expected,
            "count": len(rows),
        }
    manifest["updated_at"] = max((r["date"] for rows in rows_by_series.values() for r in rows[-1:]), default=None)
    return manifest


def write_macro_history(writer: Any, series_history: dict[str, list[dict[str, Any]]], groups: dict[str, list[str]]) -> dict[str, int]:
    """Persist the two layers. ``series_history`` is keyed lowercase (collector convention);
    series ids are uppercased for the catalog/group lookups. Only ROSTER series are
    archived — internal anchors (the EFFR FedWatch fallback) are not published series and
    must not leak into a bundle (review: an unmapped id used to write None.30d.json).
    Returns per-layer file counts.
    """
    rows_by_series: dict[str, list[dict[str, Any]]] = {
        sid.upper(): rows for sid, rows in series_history.items() if rows
    }
    if not rows_by_series:
        return {"archive": 0, "bundles": 0}

    group_of = _group_of_series(groups)

    # Layer 1: per-series append-only archive (existing write_slices convention).
    archive_count = 0
    for series, rows in rows_by_series.items():
        if series not in group_of:
            continue  # internal anchor (EFFR) — never a published archive
        writer.write_slices(f"macro/{series}", rows)
        archive_count += 1

    # Layer 2: per-group 30d/90d bundles + manifest (roster series only).
    by_group: dict[str, list[str]] = {g: [] for g in groups}
    for series in rows_by_series:
        group = group_of.get(series)
        if group is not None:
            by_group.setdefault(group, []).append(series)

    macro_dir = writer.history_dir / "macro"
    bundle_count = 0
    for group, series_list in by_group.items():
        rows = {s: rows_by_series[s] for s in series_list if s in rows_by_series}
        for slice_name in SLICES:
            window = 30 if slice_name == "30d" else 90
            sliced = {s: r[-window:] for s, r in rows.items()}
            writer.write_json(macro_dir / f"{group}.{slice_name}.json", build_bundle(sliced))
            bundle_count += 1
    writer.write_json(macro_dir / "index.json", build_manifest(rows_by_series, groups))
    return {"archive": archive_count, "bundles": bundle_count}


def _group_of_series(groups: dict[str, list[str]]) -> dict[str, str]:
    """One series → group map, built once per call (was duplicated in two methods, #96 review)."""
    return {s: g for g, ss in groups.items() for s in ss}
