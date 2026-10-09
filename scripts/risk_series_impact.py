#!/usr/bin/env python3
"""Measure the on/off delta of the derived-value-history gate (#D3).

``scoring.derived_history.enabled`` decides whether the computed indicators (breadth / trend /
realized vol) are scored from a derived value history — the same percentile primary path the
FRED inputs use — instead of the hand-drawn ``HEURISTIC_RULES`` table. Three of them are in
neither table, so switching the gate also removes real dead weight. That means flipping it
*moves published scores*, which is why it ships OFF and why calibration owns the decision
rather than the data wiring. This script produces the evidence that decision needs: it replays
one point-in-time panel twice through the governed production replay
(``pipeline.risk.calibration.replay_production_path``) — once with the gate off, once with it
on — and reports exactly what moved.

  python scripts/risk_series_impact.py
  python scripts/risk_series_impact.py --panel artifacts/calibration/panel.json

The second configuration is materialized as a real config file in a temporary directory rather
than patched in memory: both replays then run the production code path unmodified against two
configs that actually exist, and neither run can silently inherit the other's settings.

Honest limits, reported rather than hidden:

- A derived series needs ``MIN_SERIES_SAMPLES`` (60) observations *after* its lookback — 200
  benchmark sessions for ``price_vs_ma200`` / ``breadth_above_ma200``, 64 for the rest. A short
  panel therefore exercises few keys. The report names every key the panel could not exercise
  and why, and says plainly when the panel is too short to measure the dead-weight keys at all.
- ``cross_asset_confirmation`` is never derived from a partial signal set (the live value is a
  hit rate over eight signals), so it stays on the constant fallback in both runs.
- ``projected_path_split`` applies the panel's derived coverage to the configured weights. It
  is a projection, not a measurement: production coverage depends on the live 1y benchmark
  window, which is longer than any deterministic CI panel.

This script is a diagnostic and is not part of the CI gate set.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.indicators.derived_series import derive_report  # noqa: E402
from pipeline.risk.calibration import (  # noqa: E402
    normalize_calibration_panel,
    replay_production_path,
)
from pipeline.risk.model import DERIVED_HISTORY_KEYS  # noqa: E402
from pipeline.risk.weight_audit import configured_indicator_weights  # noqa: E402

#: The config key this script varies. Named once so the report cannot drift from the code.
GATE_KEY = "scoring.derived_history.enabled"

#: The key whose definition cannot be replayed from a partial signal set (see the module doc).
NEVER_DERIVED = "cross_asset_confirmation"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _panel_histories(normalized: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The panel's market columns as a symbol → rows history (as of the final panel date).

    Mirrors ``calibration._point_in_time_market_history`` at the last index, so the derived
    feasibility reported here is the coverage the replay itself could have reached.
    """
    dates = normalized["dates"]
    return {
        symbol.upper(): [
            {"date": dates[index], "close": value}
            for index, value in enumerate(values)
            if value is not None
        ]
        for symbol, values in normalized["market"].items()
    }


def _panel_series_history(normalized: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The panel's macro columns as a series → rows history (as of the final panel date)."""
    dates = normalized["dates"]
    return {
        key: [
            {"date": dates[index], "value": value}
            for index, value in enumerate(values)
            if value is not None
        ]
        for key, values in normalized["macro"].items()
    }


def _settings_for(config_source: Path, work_dir: Path, enabled: bool) -> Any:
    """Materialize ``config/risk_model.yaml`` with the gate set to ``enabled``, and load it."""
    import yaml

    from pipeline.settings import Settings

    raw = yaml.safe_load(config_source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"risk model config must be a YAML mapping: {config_source}")
    scoring = raw.setdefault("scoring", {})
    scoring["derived_history"] = {"enabled": enabled}
    (work_dir / "risk_model.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return Settings(config_dir=work_dir)


def _numbers(rows: dict[str, dict[str, Any]], field: str) -> list[float]:
    return [float(row[field]) for row in rows.values()]


def _score_delta(off: dict[str, dict[str, Any]], on: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare two replays date by date; the dates must match or the comparison is meaningless."""
    if set(off) != set(on):
        return {
            "observations": 0,
            "error": (
                "the two replays scored different dates "
                f"(off={len(off)}, on={len(on)}); no delta was computed"
            ),
        }
    deltas = [
        (date_value, float(on[date_value]["total_score"]) - float(off[date_value]["total_score"]))
        for date_value in sorted(off)
    ]
    if not deltas:
        return {"observations": 0, "error": "the panel produced no scored observations"}
    magnitudes = [abs(delta) for _, delta in deltas]
    worst_date, worst_delta = max(deltas, key=lambda item: abs(item[1]))
    off_scores = _numbers(off, "total_score")
    on_scores = _numbers(on, "total_score")
    level_changes = [
        {
            "date": date_value,
            "from": off[date_value]["risk_level"],
            "to": on[date_value]["risk_level"],
        }
        for date_value in sorted(off)
        if off[date_value]["risk_level"] != on[date_value]["risk_level"]
    ]
    return {
        "observations": len(deltas),
        "changed": sum(1 for magnitude in magnitudes if magnitude > 1e-9),
        "mean_abs": round(sum(magnitudes) / len(magnitudes), 4),
        "max_abs": round(max(magnitudes), 4),
        "max_abs_date": worst_date,
        "max_abs_signed": round(worst_delta, 4),
        "mean_signed": round(sum(delta for _, delta in deltas) / len(deltas), 4),
        "range_off": [round(min(off_scores), 2), round(max(off_scores), 2)],
        "range_on": [round(min(on_scores), 2), round(max(on_scores), 2)],
        "risk_level_changes": level_changes,
    }


def _path_totals(artifact: dict[str, Any]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in artifact["observations"]:
        for path, count in (row.get("indicator_path_counts") or {}).items():
            totals[path] = totals.get(path, 0) + int(count)
    return dict(sorted(totals.items()))


def _projected_path_split(
    weights: list[Any], derived_observed: set[str]
) -> dict[str, Any]:
    """Apply the derived coverage to the configured weights (a projection, see the module doc).

    Uses the same global-weight normalization the published ``top_drivers`` use, so
    ``dead_weight`` here is directly comparable with ``scripts/risk_weight_audit.py``.
    """
    by_path: dict[str, dict[str, Any]] = {
        "percentile": {"keys": [], "global_weight": 0.0},
        "heuristic": {"keys": [], "global_weight": 0.0},
        "unmapped": {"keys": [], "global_weight": 0.0},
    }
    for item in weights:
        path = item.scoring_path
        if path == "heuristic" and item.key in derived_observed:
            path = "percentile"
        by_path[path]["keys"].append(item.key)
        by_path[path]["global_weight"] = round(
            by_path[path]["global_weight"] + item.global_weight, 4
        )
    return {
        "by_path": {
            path: {**bucket, "keys": sorted(bucket["keys"])} for path, bucket in by_path.items()
        },
        "dead_weight": round(by_path["unmapped"]["global_weight"], 2),
        "heuristic_weight": round(by_path["heuristic"]["global_weight"], 2),
        "percentile_weight": round(by_path["percentile"]["global_weight"], 2),
    }


def run(panel_path: Path, config_source: Path, out_path: Path) -> int:
    import yaml

    panel = _load_json(panel_path)
    normalized = normalize_calibration_panel(panel)
    config_raw = yaml.safe_load(config_source.read_text(encoding="utf-8"))
    if not isinstance(config_raw, dict):
        raise ValueError(f"risk model config must be a YAML mapping: {config_source}")
    weights = configured_indicator_weights(config_raw)

    with tempfile.TemporaryDirectory(prefix="risk-series-impact-") as tmp:
        root = Path(tmp)
        off_dir = root / "off"
        on_dir = root / "on"
        off_dir.mkdir()
        on_dir.mkdir()
        off_artifact = replay_production_path(panel, _settings_for(config_source, off_dir, False))
        on_artifact = replay_production_path(panel, _settings_for(config_source, on_dir, True))

        off_rows = {row["date"]: row for row in off_artifact["observations"]}
        on_rows = {row["date"]: row for row in on_artifact["observations"]}
        delta = _score_delta(off_rows, on_rows)

        derived = derive_report(
            _panel_histories(normalized), _panel_series_history(normalized)
        )
        observed = set(derived["derived_keys"])
        not_exercised = [
            {
                "key": key,
                "reason": detail.get("reason"),
                "detail": detail.get("detail"),
                "observations": detail.get("observations"),
                "required_observations": detail.get("required_observations"),
            }
            for key, detail in sorted(derived["withheld"].items())
        ]
        exercised_gate_keys = sorted(observed & DERIVED_HISTORY_KEYS)
        blocked_gate_keys = sorted(DERIVED_HISTORY_KEYS - observed - {NEVER_DERIVED})

        report = {
            "artifact": "risk_series_impact",
            "artifact_version": "1.0.0",
            "generated_at": date.today().isoformat(),
            "gate": {
                "config_key": GATE_KEY,
                "off": {
                    "input_fingerprint": off_artifact["input_fingerprint"],
                    "observations": len(off_rows),
                },
                "on": {
                    "input_fingerprint": on_artifact["input_fingerprint"],
                    "observations": len(on_rows),
                },
            },
            "panel": {
                "source": str(panel_path),
                "mode": str((normalized.get("source_metadata") or {}).get("mode", "unspecified")),
                "dates": len(normalized["dates"]),
                "evaluated": sum(1 for value in normalized["evaluate"] if value),
                "first_date": normalized["dates"][0],
                "last_date": normalized["dates"][-1],
                "market_symbols": sorted(normalized["market"]),
            },
            "score_delta": delta,
            "scoring_path_counts": {
                "off": _path_totals(off_artifact),
                "on": _path_totals(on_artifact),
            },
            "derived_series": {
                "benchmark": derived["benchmark"],
                "benchmark_observations": derived["benchmark_observations"],
                "universe_symbols": derived["universe_symbols"],
                "exercised": exercised_gate_keys,
                "not_exercised": not_exercised,
                "observed": derived["observed"],
            },
            "projected_path_split": _projected_path_split(weights, observed),
            "measurement_limits": [],
        }

    if not exercised_gate_keys:
        report["measurement_limits"].append(
            "the panel could not derive a single value series, so the two replays are "
            "identical by construction — this panel cannot measure the gate"
        )
    elif blocked_gate_keys:
        report["measurement_limits"].append(
            "the panel is too short to exercise "
            + ", ".join(blocked_gate_keys)
            + "; their move off the heuristic table is not measured here"
        )
    if NEVER_DERIVED not in observed:
        report["measurement_limits"].append(
            f"{NEVER_DERIVED} is never derived from a partial signal set, so it stays on the "
            "constant fallback in both runs (its 15% weight is unaffected by this gate)"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(_render(report, out_path))
    return 0


def _render(report: dict[str, Any], out_path: Path) -> str:
    delta = report["score_delta"]
    lines = [
        "Derived-value-history gate impact (#D3)",
        "=" * 78,
        f"gate: {report['gate']['config_key']}  off -> on",
        f"panel: {report['panel']['source']} ({report['panel']['mode']})",
        f"       {report['panel']['dates']} dates, {report['panel']['evaluated']} evaluated, "
        f"{report['panel']['first_date']} .. {report['panel']['last_date']}",
    ]
    if delta.get("error"):
        lines.append(f"score delta: NOT COMPUTED — {delta['error']}")
    else:
        lines += [
            f"score delta: {delta['observations']} observations, {delta['changed']} changed",
            f"             mean|delta|={delta['mean_abs']} max|delta|={delta['max_abs']} "
            f"on {delta['max_abs_date']} (signed {delta['max_abs_signed']:+})",
            f"             mean signed delta={delta['mean_signed']:+}  "
            f"range off={delta['range_off']} on={delta['range_on']}",
            f"             risk-level changes: {len(delta['risk_level_changes'])}",
        ]
    paths = report["scoring_path_counts"]
    lines += [
        "",
        "scoring paths observed in the replay (indicator-days):",
        f"  off: {paths['off']}",
        f"  on:  {paths['on']}",
        "",
        f"derived value series: benchmark={report['derived_series']['benchmark']} "
        f"({report['derived_series']['benchmark_observations']} sessions), "
        f"universe={report['derived_series']['universe_symbols']} symbols",
        f"  exercised ({len(report['derived_series']['exercised'])}): "
        + (", ".join(report["derived_series"]["exercised"]) or "none"),
    ]
    for item in report["derived_series"]["not_exercised"]:
        lines.append(
            f"  withheld  {item['key']:24s} {str(item['reason']):22s} {item['detail']}"
        )
    split = report["projected_path_split"]
    lines += [
        "",
        "projected path split over configured weights (projection, not a measurement):",
        f"  percentile={split['percentile_weight']:.2f}w heuristic={split['heuristic_weight']:.2f}w "
        f"unmapped={split['dead_weight']:.2f}w dead weight",
    ]
    if report["measurement_limits"]:
        lines += ["", "measurement limits:"]
        lines += [f"  - {item}" for item in report["measurement_limits"]]
    lines += ["", f"[risk-series-impact] wrote {out_path}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the derived-value-history gate delta on a point-in-time panel"
    )
    parser.add_argument(
        "--panel",
        type=Path,
        default=Path("tests/fixtures/calibration_panel.json"),
        help="point-in-time panel replayed with the gate off and on",
    )
    parser.add_argument(
        "--risk-model",
        type=Path,
        default=Path("config/risk_model.yaml"),
        help="shipped risk model config; the gate is set to true in a temporary copy",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="artifact path (default: artifacts/risk/series-impact-<YYYY-MM-DD>.json)",
    )
    args = parser.parse_args(argv)

    for path in (args.panel, args.risk_model):
        if not path.exists():
            print(f"[risk-series-impact] missing input: {path}", file=sys.stderr)
            return 2

    out = args.out or Path("artifacts") / "risk" / f"series-impact-{date.today().isoformat()}.json"
    return run(args.panel, args.risk_model, out)


if __name__ == "__main__":
    raise SystemExit(main())
