"""#64: freshness has one author.

The only code that produces a freshness status is
:func:`pipeline.validation.freshness.finalize_freshness`; the collectors return payloads and
provider outcome, and the caller (run.py via :func:`pipeline.schemas.envelope.assemble_envelope`)
finalises. These tests pin that invariant and the two behaviours it buys: a degraded run
publishes a non-fresh risk dataset, and every envelope is assembled through the one path.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
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
            breadth=None,
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
            breadth=None,
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
        breadth=None,
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
    assert finalize_freshness("crypto", None, True).status == "missing"
    assert finalize_freshness("crypto", None, False).status == "missing"
    assert finalize_freshness("crypto", "2026-08-04T12:00:00Z", True).status == "degraded"

    # #89: the reason distinguishes the two ways of being missing, which the status alone
    # cannot. "every provider failed" and "we never asked" both used to read `missing`.
    assert finalize_freshness("crypto", None, True).reason.code == "all_providers_failed"
    assert finalize_freshness("crypto", None, False).reason.code == "not_collected_this_run"


def test_fresh_requires_a_non_empty_payload() -> None:
    """#89 / E-2: the invariant that closed the "empty but fresh" hole.

    `calendar.json` shipped `freshness_status: "fresh"` with `events: []` for weeks. A dataset
    that returned no rows is `empty` — a real state with its own badge — never `fresh`.
    """
    now = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)
    now_iso = "2026-08-04T11:00:00Z"
    verdict = finalize_freshness("calendar", now_iso, False, row_count=0, now=now)
    assert verdict.status == "empty"
    assert verdict.reason.code == "no_events_in_window"

    # Non-calendar datasets get the generic code; the distinction is worth keeping because a
    # quiet calendar week is normal and an equities feed with zero rows is not.
    assert (
        finalize_freshness("equities", now_iso, False, row_count=0, now=now).reason.code
        == "no_rows_returned"
    )

    # Empty *and* degraded is not a quiet week, it is a failure that happens to look like one.
    assert finalize_freshness("calendar", now_iso, True, row_count=0, now=now).status == "missing"

    # row_count=None means "cardinality is not a meaningful question here" (risk, dashboard).
    assert finalize_freshness("risk", now_iso, False, row_count=None, now=now).status == "fresh"


def test_degraded_reason_names_the_mechanism() -> None:
    """A degraded dataset says *why* it degraded, not just that it did (#89, E-1).

    Eight datasets used to publish the literal string "degraded" as their own explanation.
    """
    now_iso = "2026-08-04T12:00:00Z"
    assert finalize_freshness("macro", now_iso, True, row_count=5, from_cache=True).reason.code == "served_from_cache"
    assert (
        finalize_freshness("macro", now_iso, True, row_count=5, used_fallback=True).reason.code
        == "served_from_fallback"
    )
    assert finalize_freshness("macro", now_iso, True, row_count=5).reason.code == "provider_http_error"


def test_unknown_reason_code_is_coerced_not_raised() -> None:
    """A provider inventing an error label must not kill the run before metadata is written."""
    verdict = finalize_freshness(
        "macro", "2026-08-04T12:00:00Z", True, row_count=1, error_code="totally_made_up"
    )
    assert verdict.reason.code == "provider_http_error"


def test_reason_detail_is_capped() -> None:
    """The free-text half is capped at 200 chars — the redaction surface stays bounded (#92)."""
    verdict = finalize_freshness(
        "macro", "2026-08-04T12:00:00Z", True, row_count=1, detail="x" * 5000
    )
    assert len(verdict.reason.detail) == 200
