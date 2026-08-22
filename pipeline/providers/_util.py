"""Small provider primitives shared by all external adapters."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _f(value: Any) -> float | None:
    """Return a finite, consistently rounded provider number."""
    try:
        number = float(value)
        return None if math.isnan(number) or math.isinf(number) else round(number, 6)
    except (TypeError, ValueError):
        return None


def _today(fmt: str = "%Y-%m-%d") -> str:
    return datetime.now(UTC).strftime(fmt)
