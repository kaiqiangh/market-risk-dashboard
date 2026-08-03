#!/usr/bin/env python3
"""Offline calibration script (Architecture §1.8: 2008/2018/2020 segments → docs/calibration-report.md).

All data is freely available: FRED VIXCLS/BAMLH0A0HYM2/DGS10 + yfinance SPX history.
Released with the repo (T05 removed the docs/ ignore); calibration boundary: the UI must not
claim "exact crash probability" before calibration is complete.

Usage: python scripts/calibration.py [--out docs/calibration-report.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fetch_fred_map(series_id: str, start: str, end: str) -> dict[str, float]:
    from pipeline.providers.fred import FredProvider
    from pipeline.settings import settings

    fred = FredProvider(settings)
    try:
        return {o["date"]: o["value"] for o in fred.get_series(series_id, start=start, end=end)}
    except Exception:  # noqa: BLE001
        return {}


def _fetch_spx_map(start: str, end: str) -> dict[str, float]:
    from pipeline.providers.yahoo import YahooProvider
    from pipeline.settings import settings

    yahoo = YahooProvider(settings)
    try:
        hist = yahoo.get_history_range("^GSPC", start=start, end=end)
    except Exception:  # noqa: BLE001
        return {}
    return {r["date"]: r["close"] for r in hist.rows if r.get("close") is not None}


def run_calibration(out_path: Path) -> int:
    from pipeline.risk.calibration import CALIBRATION_WINDOWS, evaluate_segment

    report_lines: list[str] = []
    report_lines.append("# Market Risk Dashboard — Offline Calibration Report")
    report_lines.append("")
    report_lines.append("**Scope statement:** The risk scores on this page are **modeled estimates of market stress**, not exact crash probabilities (Architecture §1.8 calibration boundary).")
    report_lines.append("")
    report_lines.append("## Methodology")
    report_lines.append("")
    report_lines.append("Run the simplified risk model on the 2008/2018/2020 windows (composite score of VIX + HY OAS + SPX drawdown),")
    report_lines.append("evaluating: early warning lead time, risk score speed, maximum drawdown, forward 5/10/20/30-day volatility, and risk-level stability.")
    report_lines.append("")
    report_lines.append("## Results")
    report_lines.append("")

    ok = True
    for segment, meta in CALIBRATION_WINDOWS.items():
        start, end = meta["start"], meta["end"]
        vix_map = _fetch_fred_map("VIXCLS", start, end)
        hy_map = _fetch_fred_map("BAMLH0A0HYM2", start, end)
        spx_map = _fetch_spx_map(start, end)
        # Align on common trading days (FRED and yfinance trading calendars are not synchronized)
        common_dates = sorted(set(vix_map) & set(hy_map) & set(spx_map)) or sorted(set(spx_map))
        if not common_dates or not spx_map:
            report_lines.append(f"### {segment} ({meta['note']}) — ⚠️ data unavailable (network/rate limit), skipped")
            report_lines.append("")
            ok = False
            continue
        vix_values = [vix_map.get(d) for d in common_dates]
        hy_values = [hy_map.get(d) for d in common_dates]
        spx_values = [spx_map[d] for d in common_dates]
        result = evaluate_segment(common_dates, vix_values, hy_values, spx_values, segment)
        report_lines.append(f"### {segment} ({meta['note']})")
        report_lines.append("")
        report_lines.append(f"- Trading days: {result['n_days']}")
        report_lines.append(f"- Max drawdown: {result['max_drawdown_pct']}%")
        report_lines.append(f"- Early warning (score ≥60 vs peak): {result['early_warning_days_vs_peak']} days (negative = warned before peak)")
        report_lines.append(f"- Risk score 40→60 speed: {result['speed_40_to_60_days']} days")
        report_lines.append(f"- Forward volatility after peak: {result['future_vol']}")
        report_lines.append(f"- Risk level switches: {result['level_switches']}")
        report_lines.append(f"- Score range: first {result['score_first']} / peak {result['score_max']} / last {result['score_last']}")
        report_lines.append("")

    report_lines.append("## Limitations")
    report_lines.append("")
    report_lines.append("- Market breadth history (2008-2012) is unavailable → this report excludes the breadth dimension (Review P0-3; T05 rebuilds it with approximations).")
    report_lines.append("- The MVP risk mapping uses heuristic rules (pipeline/risk/scoring.py), not a statistical model.")
    report_lines.append("- Free data sources have no SLA; backtest windows may be skipped when network data is unavailable.")
    report_lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[calibration] Report written to {out_path}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline calibration: 2008/2018/2020 → docs/calibration-report.md")
    parser.add_argument("--out", type=Path, default=Path("docs/calibration-report.md"))
    args = parser.parse_args()
    return run_calibration(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
