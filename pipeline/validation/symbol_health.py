"""Read-only theme symbol health gate (#175).

Root-cause follow-up to #171: two delisted theme symbols (ABB, FI) silently degraded
sectors → market → dashboard → factlayer → analysis for weeks before anyone noticed.
This module is a periodic health gate that fails loudly whenever the latest committed
run telemetry shows a configured theme symbol as missing or degraded.

Canonical theme-symbol set
--------------------------
Derived from ``config/themes.yaml`` using the SAME predicate as
``MarketCollector._theme_history_symbols`` (pipeline/collectors/market.py): for every
theme in ``themes.sectors.values()`` + ``themes.themes.values()``, an ``etf`` proxy
symbol is required; otherwise every constituent symbol that does not end with
``.SH``/``.SZ`` (CN excluded — akshare's historical kline tier is blocked per #85) is
required. Both sides read the same YAML with the same predicate, so the check and the
collector cannot drift.

Evidence
--------
Reads the committed ``<data-dir>/metadata/sources.json`` and takes
``domains.market.collection_telemetry.missing_inputs`` and ``.degraded_inputs`` (each a
list of ``{request_key, domain, symbol, consumers, status}`` entries). Symbols appearing
there with ``"themes"`` in ``consumers`` are the failed inputs.

Verdict
-------
* If ``metadata/sources.json`` is absent/unreadable, or the market domain /
  ``collection_telemetry`` is absent → print a note and exit 0 (partial/news-only data
  states and corrupt-file states already reported by ci_checks must not break this gate).
* Else failed = (canonical theme symbols ∩ telemetry-failed symbols). Non-empty → print
  ``theme symbol health: missing/degraded in latest run telemetry: <symbols>`` and exit 1.
* Empty → print ``theme symbol health: ok`` and exit 0.

The module is self-contained and has no side effects on import (config loading is lazy
inside the functions), matching the ``ci_checks`` argument conventions:
``python -m pipeline.validation.symbol_health --data-dir <dir>``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: Telemetry buckets that name inputs the collector could not serve fresh.
_FAILED_TELEMETRY_KEYS: tuple[str, ...] = ("missing_inputs", "degraded_inputs")


def canonical_theme_symbols() -> set[str]:
    """The non-CN series symbols required by the configured themes.

    Same predicate as ``MarketCollector._theme_history_symbols``: an ``etf`` proxy symbol
    for a theme replaces its constituents; basket themes (no ETF proxy, or ``kind: basket``)
    contribute every constituent that is not a CN ``.SH``/``.SZ`` symbol (#85).
    """
    from pipeline.settings import Settings

    themes = Settings().load_themes_config()
    symbols: set[str] = set()
    for theme in [*themes.sectors.values(), *themes.themes.values()]:
        if theme.proxy is not None and theme.proxy.kind == "etf" and theme.proxy.symbol:
            symbols.add(theme.proxy.symbol)
        else:
            symbols |= {c.symbol for c in theme.constituents if not c.symbol.endswith((".SH", ".SZ"))}
    return symbols


def telemetry_failed_symbols(data: dict[str, Any]) -> set[str]:
    """Symbols named in missing/degraded run telemetry for the ``themes`` consumer.

    The market collector publishes ``missing_inputs``/``degraded_inputs`` as lists of
    ``{request_key, domain, symbol, consumers, status}``; only entries whose consumers
    include ``"themes"`` are evidence for this gate.
    """
    domains = data.get("domains")
    if not isinstance(domains, dict):
        return set()
    market = domains.get("market")
    if not isinstance(market, dict):
        return set()
    telemetry = market.get("collection_telemetry")
    if not isinstance(telemetry, dict):
        return set()

    failed: set[str] = set()
    for key in _FAILED_TELEMETRY_KEYS:
        entries = telemetry.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            consumers = entry.get("consumers")
            if not isinstance(consumers, list) or "themes" not in consumers:
                continue
            symbol = entry.get("symbol")
            if isinstance(symbol, str) and symbol:
                failed.add(symbol)
    return failed


def check(data_dir: Path) -> tuple[int, str]:
    """Run the gate over one data tree; returns ``(exit_code, message)``.

    ``exit_code`` is 0 = healthy (or unassessable note), 1 = a canonical theme symbol is
    missing/degraded in the latest run telemetry.
    """
    sources_path = data_dir / "metadata" / "sources.json"
    if not sources_path.exists():
        return 0, (
            f"theme symbol health: note — {sources_path} absent; "
            "gate skipped (partial/news-only data state)"
        )
    try:
        data = json.loads(sources_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # A corrupt sources.json is a data-quality failure already reported by ci_checks
        # ("metadata/sources.json: parse failed"); this read-only gate does not add a second
        # failure path for a file it cannot assess.
        return 0, f"theme symbol health: note — {sources_path} unreadable ({exc}); gate skipped"

    domains = data.get("domains")
    market = domains.get("market") if isinstance(domains, dict) else None
    telemetry = market.get("collection_telemetry") if isinstance(market, dict) else None
    if not isinstance(telemetry, dict):
        return 0, (
            "theme symbol health: note — market collection_telemetry absent; "
            "gate skipped (partial/news-only data state)"
        )

    failed = sorted(canonical_theme_symbols() & telemetry_failed_symbols(data))
    if failed:
        return 1, (
            "theme symbol health: missing/degraded in latest run telemetry: "
            + ", ".join(failed)
        )
    return 0, "theme symbol health: ok"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point, mirroring ``ci_checks.main`` argument conventions."""
    parser = argparse.ArgumentParser(
        description="Theme symbol health gate: fails when a configured theme symbol is missing/degraded in the latest run telemetry"
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="public/data directory (default: settings.data_dir)")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        data_dir = args.data_dir
    else:
        from pipeline.settings import settings

        data_dir = settings.data_dir

    code, message = check(data_dir)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
