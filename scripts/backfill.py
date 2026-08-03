#!/usr/bin/env python3
"""Backfill warm-up script (Architecture §1.7: one-time backfill of 30-90 days of market/macro history, except FedWatch).

Usage: python scripts/backfill.py [--days 90]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run import _run_backfill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill warm-up of 30-90 days of history")
    parser.add_argument("--days", type=int, default=90, help="Number of backfill days (default 90)")
    args = parser.parse_args()
    print(f"Backfill window: last {args.days} days (market/macro; FedWatch accumulates from launch date)")
    return _run_backfill()


if __name__ == "__main__":
    raise SystemExit(main())
