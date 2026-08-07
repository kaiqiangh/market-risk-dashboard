#!/usr/bin/env python3
"""Fallback-provider liveness check (#100): build the real registry and probe every
fallback's health(). A dead fallback exits non-zero — run by the scheduled
fallback-health workflow so a fallback nobody exercises cannot rot unnoticed.

Usage:  python -m scripts.check_fallbacks   (or scripts/check-fallbacks.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as `python scripts/check_fallbacks.py` from anywhere in the repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.providers import build_default_providers
from pipeline.providers.fallback_health import check_fallbacks, render_check
from pipeline.settings import Settings


def main() -> int:
    providers = build_default_providers(Settings())
    result = check_fallbacks(providers)
    print(render_check(result))
    if result.dead:
        print("\n[check-fallbacks] FAILED: dead fallback provider(s) — the degradation "
              "chain is one outage away from cache-or-nothing.", file=sys.stderr)
        for probe in result.dead:
            print(f"  {probe.domain}/{probe.provider}: {probe.error}", file=sys.stderr)
        return 1
    print("[check-fallbacks] result: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
