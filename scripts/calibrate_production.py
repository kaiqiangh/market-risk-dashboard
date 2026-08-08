#!/usr/bin/env python3
"""Run a point-in-time replay of the production Risk Lab path.

Examples:
  python scripts/calibrate_production.py --panel tests/fixtures/calibration_panel.json
  python scripts/calibrate_production.py --start 2015-01-01 --end 2024-12-31 --regime mixed

The panel mode is deterministic and is the CI gate. Without ``--panel`` this command fetches
latest FRED/Yahoo observations, adds a five-year warm-up, and writes the fetched panel when
``--panel-out`` is supplied so the exact input can be replayed later.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.risk.calibration import (
    CALIBRATION_MACRO_GROUPS,
    CALIBRATION_MARKET_SYMBOLS,
    normalize_calibration_panel,
    replay_production_path,
)


def _asof_values(rows: dict[str, float], dates: list[str]) -> list[float | None]:
    ordered = sorted(rows.items())
    cursor = 0
    latest: float | None = None
    values: list[float | None] = []
    for target in dates:
        while cursor < len(ordered) and ordered[cursor][0] <= target:
            latest = ordered[cursor][1]
            cursor += 1
        values.append(latest)
    return values


def _fetch_fred(series_id: str, start: str, end: str) -> dict[str, float]:
    from pipeline.providers.fred import FredProvider
    from pipeline.settings import settings

    try:
        rows = FredProvider(settings).get_series(series_id, start=start, end=end)
    except Exception:  # noqa: BLE001 — the artifact records missing source observations
        return {}
    return {str(row["date"]): float(row["value"]) for row in rows if row.get("value") is not None}


def _fetch_yahoo(symbol: str, start: str, end: str) -> dict[str, float]:
    from pipeline.providers.yahoo import YahooProvider
    from pipeline.settings import settings

    try:
        rows = YahooProvider(settings).get_history_range(symbol, start=start, end=end).rows
    except Exception:  # noqa: BLE001 — the artifact records missing source observations
        return {}
    return {str(row["date"]): float(row["close"]) for row in rows if row.get("close") is not None}


def fetch_panel(start: str, end: str, warmup_years: int, regime: str) -> dict[str, Any]:
    requested_start = date.fromisoformat(start)
    fetch_start = requested_start - timedelta(days=365 * warmup_years)
    macro_maps = {
        key: _fetch_fred(key.upper(), fetch_start.isoformat(), end)
        for key in CALIBRATION_MACRO_GROUPS
    }
    market_maps = {
        symbol: _fetch_yahoo(symbol, fetch_start.isoformat(), end)
        for symbol in CALIBRATION_MARKET_SYMBOLS
    }
    if not market_maps["SPY"]:
        raise RuntimeError("SPY history was unavailable; no production-path calibration panel was built")
    dates = sorted(market_maps["SPY"])
    return {
        "panel_version": "1.0.0",
        "dates": dates,
        "evaluate": [value >= start for value in dates],
        "regimes": [regime if value >= start else "warmup" for value in dates],
        "macro": {key: _asof_values(values, dates) for key, values in macro_maps.items()},
        "market": {symbol: [values.get(value) for value in dates] for symbol, values in market_maps.items()},
        "source_metadata": {
            "mode": "live_fetch",
            "requested_start": start,
            "requested_end": end,
            "warmup_start": fetch_start.isoformat(),
            "sources": {"macro": "FRED latest observations", "market": "Yahoo Finance adjusted history"},
            "revision_policy": "latest source observations; no point-in-time vintage data available",
            "missing_observations_policy": "missing observations remain null and reduce replay coverage",
        },
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time production-path Risk Lab calibration")
    parser.add_argument("--panel", type=Path, help="deterministic or previously fetched panel JSON")
    parser.add_argument("--panel-out", type=Path, help="write the live-fetched input panel for later replay")
    parser.add_argument("--out", type=Path, default=Path("artifacts/calibration/production-path.json"))
    parser.add_argument("--start", default="2015-01-01", help="evaluation start when fetching live data")
    parser.add_argument("--end", default="2024-12-31", help="evaluation end when fetching live data")
    parser.add_argument("--warmup-years", type=int, default=5)
    parser.add_argument("--regime", default="unclassified", help="regime label for live-fetched evaluation rows")
    args = parser.parse_args(argv)

    if args.panel:
        panel = json.loads(args.panel.read_text(encoding="utf-8"))
    else:
        if args.warmup_years < 0:
            parser.error("--warmup-years must be non-negative")
        panel = fetch_panel(args.start, args.end, args.warmup_years, args.regime)
        if args.panel_out:
            _write_json(args.panel_out, panel)

    artifact = replay_production_path(panel)
    # Re-run validation at the CLI boundary so malformed panel files fail before an artifact
    # is published; the replay itself also validates before scoring.
    normalize_calibration_panel(panel)
    _write_json(args.out, artifact)
    horizon_20 = artifact["metrics"]["horizons"]["20"]["coverage"]
    print(
        f"[calibration] wrote {args.out} | observations={len(artifact['observations'])} "
        f"h20_outcomes={horizon_20['outcome_available']} paths={artifact['path_counts']}"
    )
    return 0 if horizon_20["outcome_available"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
