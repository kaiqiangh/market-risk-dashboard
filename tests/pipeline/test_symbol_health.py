"""Theme symbol health gate tests (pipeline/validation/symbol_health.py, #175).

Every test writes a synthetic ``metadata/sources.json`` under ``tmp_path`` — never the
published data directory. The canonical theme-symbol set is read from the real
``config/themes.yaml``, so these tests pin the gate to the collector's predicate by
construction (same YAML, same predicate as ``MarketCollector._theme_history_symbols``).

Covers: healthy telemetry → exit 0; a canonical symbol missing → exit 1 + named in
output; a canonical symbol degraded → exit 1; absent telemetry (no market domain / no
collection_telemetry / no sources.json) → exit 0 with a note; CN ``.SH``/``.SZ``
symbols never flagged; non-theme consumers never flagged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.validation.symbol_health import canonical_theme_symbols, main


def _telemetry_entry(symbol: str, *, consumers: list[str] | None = None, status: str = "missing") -> dict[str, Any]:
    """One entry in the collector's missing/degraded telemetry shape (see market.py)."""
    return {
        "request_key": f"hist_{symbol}_1y",
        "domain": "quotes",
        "symbol": symbol,
        "consumers": consumers or ["themes"],
        "status": status,
    }


def _write_sources(
    data_dir: Path,
    *,
    missing: list[dict[str, Any]] | None = None,
    degraded: list[dict[str, Any]] | None = None,
    with_market_domain: bool = True,
    with_telemetry: bool = True,
) -> Path:
    """Write a synthetic sources.json and return its path."""
    missing = missing or []
    degraded = degraded or []
    market: dict[str, Any] = {"degraded": False, "status": "ok", "reason": "", "datasets": {}, "provider": "fmp", "providers": {}}
    if with_telemetry:
        market["collection_telemetry"] = {
            "history_plan_count": 0,
            "history_request_count": 0,
            "request_keys": [],
            "unique_request_keys": 0,
            "duplicate_request_keys": 0,
            "history_requests": [],
            "missing_inputs": missing,
            "degraded_inputs": degraded,
        }
    domains: dict[str, Any] = {}
    if with_market_domain:
        domains["market"] = market
    sources = {"schema_version": "1.0.0", "domains": domains}
    path = data_dir / "metadata" / "sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sources), encoding="utf-8")
    return path


def test_healthy_telemetry_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No canonical theme symbol in missing/degraded telemetry → healthy, exit 0."""
    data_dir = tmp_path / "data"
    _write_sources(data_dir, missing=[], degraded=[])

    code = main(["--data-dir", str(data_dir)])
    out = capsys.readouterr().out

    assert code == 0
    assert "theme symbol health: ok" in out


def test_missing_canonical_symbol_fails_and_names_symbol(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A canonical theme symbol in missing_inputs → exit 1 AND the symbol named in output."""
    symbol = sorted(canonical_theme_symbols())[0]
    data_dir = tmp_path / "data"
    _write_sources(data_dir, missing=[_telemetry_entry(symbol)])

    code = main(["--data-dir", str(data_dir)])
    out = capsys.readouterr().out

    assert code == 1
    assert symbol in out
    assert "missing/degraded in latest run telemetry" in out


def test_degraded_canonical_symbol_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A canonical theme symbol in degraded_inputs is the same failure as missing."""
    symbol = sorted(canonical_theme_symbols())[0]
    data_dir = tmp_path / "data"
    _write_sources(data_dir, degraded=[_telemetry_entry(symbol, status="degraded")])

    code = main(["--data-dir", str(data_dir)])

    assert code == 1
    assert symbol in capsys.readouterr().out


def test_absent_market_domain_passes_with_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No market domain at all (news-only run) → pass with a note, not a failure."""
    data_dir = tmp_path / "data"
    _write_sources(data_dir, with_market_domain=False)

    code = main(["--data-dir", str(data_dir)])
    out = capsys.readouterr().out

    assert code == 0
    assert "note" in out


def test_absent_collection_telemetry_passes_with_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Market domain present but no collection_telemetry → pass with a note."""
    data_dir = tmp_path / "data"
    _write_sources(data_dir, with_telemetry=False)

    code = main(["--data-dir", str(data_dir)])
    out = capsys.readouterr().out

    assert code == 0
    assert "note" in out


def test_missing_sources_file_passes_with_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No committed sources.json (pre-first-run state) → pass with a note."""
    code = main(["--data-dir", str(tmp_path / "data")])
    out = capsys.readouterr().out

    assert code == 0
    assert "note" in out


def test_cn_suffix_symbols_never_flagged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CN .SH/.SZ symbols are excluded from the canonical set by construction (#85)."""
    data_dir = tmp_path / "data"
    _write_sources(
        data_dir,
        missing=[_telemetry_entry("600519.SH"), _telemetry_entry("000001.SZ")],
    )

    code = main(["--data-dir", str(data_dir)])

    assert code == 0
    assert "600519.SH" not in capsys.readouterr().out


def test_non_canonical_symbol_not_flagged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A delisted symbol no longer configured in themes.yaml (ABB, #171) stays green."""
    data_dir = tmp_path / "data"
    _write_sources(data_dir, missing=[_telemetry_entry("ABB"), _telemetry_entry("FI")])

    code = main(["--data-dir", str(data_dir)])

    assert code == 0
    assert "ok" in capsys.readouterr().out


def test_non_themes_consumer_not_flagged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Telemetry for another consumer (e.g. equity_card) is not evidence for this gate."""
    symbol = sorted(canonical_theme_symbols())[0]
    data_dir = tmp_path / "data"
    _write_sources(data_dir, missing=[_telemetry_entry(symbol, consumers=["equity_card"])])

    code = main(["--data-dir", str(data_dir)])

    assert code == 0
    assert "ok" in capsys.readouterr().out
