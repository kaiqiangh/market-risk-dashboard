#!/usr/bin/env python3
"""预热回填脚本（架构 §1.7：一次性回填 30-90 天行情/宏观历史，FedWatch 除外）。

用法：python scripts/backfill.py [--days 90]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.run import _run_backfill  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="预热回填 30-90 天历史")
    parser.add_argument("--days", type=int, default=90, help="回填天数（默认 90）")
    args = parser.parse_args()
    print(f"回填窗口：最近 {args.days} 天（行情/宏观；FedWatch 从上线日起累积）")
    return _run_backfill()


if __name__ == "__main__":
    raise SystemExit(main())
