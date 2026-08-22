#!/usr/bin/env python3
"""Backfill warm-up script (Architecture §1.7: warm-up of 30-90 days of market history, except FedWatch).

Usage: python scripts/backfill.py [--days 90]

--days is honored end to end (#188): the window maps to the coarsest provider period that
covers it (see pipeline.run._period_for_days), so asking for 30 days no longer silently
spends a year of provider quota.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run import run_backfill  # noqa: E402  (public seam, not underscore-private)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill warm-up of market history (default 90 days)")
    parser.add_argument("--days", type=int, default=90, help="Number of backfill days (default 90)")
    args = parser.parse_args(argv)
    print(f"Backfill window: last {args.days} days (market; FedWatch accumulates from launch date)")
    return run_backfill(args.days)


if __name__ == "__main__":
    raise SystemExit(main())
