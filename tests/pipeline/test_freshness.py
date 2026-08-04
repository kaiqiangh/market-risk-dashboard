"""#64: freshness has one author.

The only code that produces a freshness status is
:func:`pipeline.validation.freshness.finalize_freshness`; the collectors return payloads and
provider outcome, and the caller (run.py via :func:`pipeline.schemas.envelope.assemble_envelope`)
finalises. These tests pin that invariant and the two behaviours it buys: a degraded run
publishes a non-fresh risk dataset, and every envelope is assembled through the one path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.risk.model import RiskModelResult
from pipeline.schemas.envelope import SCHEMA_VERSION, assemble_envelope
from pipeline.schemas.risk import RiskEnvelope
from pipeline.validation.freshness import finalize_freshness

COLLECTORS_DIR = Path(__file__).resolve().parents[2] / "pipeline" / "collectors"


def test_no_collector_assigns_freshness() -> None:
    """`grep -rn "freshness_status" pipeline/collectors/` returns no assignment.

    Before #64 each collector assigned `freshness_status="degraded" if self.degraded
    else "fresh"` inline while building its envelope. That made freshness have five authors.
    """
    hits: list[str] = []
    for path in sorted(COLLECTORS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"freshness_status\s*=", line):
                hits.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not hits, "collectors must not assign freshness_status; found:\n" + "\n".join(hits)


def test_degraded_run_publishes_non_fresh_risk() -> None:
    """A degraded run yields a risk envelope whose freshness is NOT `fresh`.

    Before the single-author change the risk envelope could certify itself as fresh via the
    schema default; the assembly path must now surface the provider outcome.
    """
    env = assemble_envelope(
        RiskEnvelope,
        RiskModelResult(
            model_version=SCHEMA_VERSION,
            generated_at="2026-08-04T12:00:00Z",
            total_score=52.3,
            risk_level="caution",
            regime="late_cycle",
            confidence=0.72,
        ),
        dataset="risk",
        degraded=True,
        provider="risk_model",
        data_quality=0.9,
    )
    assert env.freshness_status != "fresh"
    assert env.freshness_status == "degraded"


def test_clean_run_publishes_fresh_risk() -> None:
    """A clean run still publishes a fresh risk envelope (no behaviour regression)."""
    env = assemble_envelope(
        RiskEnvelope,
        RiskModelResult(
            model_version=SCHEMA_VERSION,
            generated_at="2026-08-04T12:00:00Z",
            total_score=52.3,
            risk_level="caution",
            regime="late_cycle",
            confidence=0.72,
        ),
        dataset="risk",
        degraded=False,
        provider="risk_model",
        data_quality=0.9,
    )
    assert env.freshness_status == "fresh"


def test_risk_envelope_inherits_base_envelope() -> None:
    """RiskEnvelope is a BaseEnvelope subclass (#64): it shares the base shape."""
    from pipeline.schemas import BaseEnvelope

    assert issubclass(RiskEnvelope, BaseEnvelope)


def test_risk_envelope_freshness_is_required() -> None:
    """Omitting freshness_status must raise — the risk card cannot certify itself fresh."""
    from pipeline.schemas import RiskModelResult

    payload = RiskModelResult(
        model_version=SCHEMA_VERSION,
        generated_at="2026-08-04T12:00:00Z",
        total_score=52.3,
        risk_level="caution",
        regime="late_cycle",
        confidence=0.72,
    )
    with pytest.raises(ValidationError):
        RiskEnvelope(
            generated_at="2026-08-04T12:00:00Z",
            schema_version=SCHEMA_VERSION,
            source=["risk_model", "fred", "yfinance"],
            source_updated_at="2026-08-04T12:00:00Z",
            data_quality=0.9,
            payload=payload,
        )


def test_risk_envelope_has_no_freshness_default() -> None:
    """The schema no longer defaults freshness to fresh (the self-certifying trap)."""
    assert "freshness_status" in RiskEnvelope.model_fields
    assert RiskEnvelope.model_fields["freshness_status"].is_required()


def test_missing_priority_over_degraded() -> None:
    """#66: a dataset with no usable data resolves to `missing` even when degraded.

    An expired-cache dataset is exactly this case: every provider failed (degraded) and
    the last-good cache was rejected as too old/undated (no data at all). The existing
    priority `missing` > `degraded` > time resolves it without a rewrite.
    """
    assert finalize_freshness("crypto", None, True) == "missing"
    assert finalize_freshness("crypto", None, False) == "missing"
    assert finalize_freshness("crypto", "2026-08-04T12:00:00Z", True) == "degraded"
