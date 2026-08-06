"""Global data Envelope (architecture §3.1).

All dataset files must be wrapped in BaseEnvelope; freshness_status is determined uniformly by
the pipeline (not trusting Provider self-reporting, architecture §8.4). This module also provides
the contract base classes and shared primitives:
- ContractModel: no implicit fields + rejects NaN/Infinity (three-artifact hard constraint, architecture §3.1)
- UTCDateTime: strict ISO 8601 UTC + Z validation
- FreshnessStatus: six-state enum
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, WithJsonSchema

#: The six freshness states. **This is the only definition** — `pipeline/validation/freshness.py`,
#: `pipeline/validation/ci_checks.py`, `scripts/validate-json.mjs` and `src/schemas/envelope.ts`
#: all derive from it (the last two via the generated `src/schemas/generated/constants.json`).
#:
#: ``empty`` is a first-class state, not a flavour of failure: the fetch succeeded and the
#: upstream answered, there are simply no rows. A quiet calendar week is ``empty``; a calendar
#: with a broken parser is ``degraded`` or ``missing``. Conflating the two is how an empty
#: dataset certified itself healthy for weeks (#89).
FreshnessStatus = Literal["fresh", "delayed", "stale", "empty", "missing", "degraded"]

#: Severity ranking of the six states — the single copy, shared by the aggregation in
#: ``validation/freshness.py`` and the domain projection in ``storage/outcomes.py``. A higher
#: rank is a *worse* (lower-confidence) status. Defined beside the literal because both
#: consumers used to carry byte-identical copies that could drift (#101). ``empty`` ranks above
#: ``stale`` but below ``degraded``: a dataset that legitimately had no rows is less trustworthy
#: than one with merely old data, but more trustworthy than one built from a fallback whose
#: provenance is second-choice.
STATUS_RANK: dict[str, int] = {
    "fresh": 0,
    "delayed": 1,
    "stale": 2,
    "empty": 3,
    "degraded": 4,
    "missing": 5,
}

#: Closed vocabulary for the machine-readable half of a freshness reason.
#:
#: The audience is the operator reading the Status page and the next agent debugging a run.
#: Because the set is closed and finite, the UI can carry one translated sentence per code
#: instead of trying to translate unbounded provider error text — and because the free-text
#: half is confined to ``FreshnessReason.detail``, redaction (#92) has exactly one target.
#:
#: All but the last code describe something that happened to a *fetch*.
#: ``input_dataset_unhealthy`` is for derived datasets (``factlayer``, ``dashboard``), whose
#: own fetch succeeded — they are only as trustworthy as their worst input, and saying "ok"
#: while aggregating a stale input is the kind of small lie this vocabulary exists to prevent.
ReasonCode = Literal[
    "ok",
    "no_rows_returned",
    "no_events_in_window",
    "provider_http_error",
    "provider_rate_limited",
    "provider_auth_failed",
    "provider_parse_error",
    "served_from_fallback",
    "served_from_cache",
    "cache_expired",
    "cache_invalid",
    "all_providers_failed",
    "not_collected_this_run",
    "interval_exceeded",
    "input_dataset_unhealthy",
]

# Data contract version (single source of truth; reused by analysis/contract.py)
SCHEMA_VERSION = "1.1.0"


def is_schema_compatible(file_version: str, current_version: str = SCHEMA_VERSION) -> bool:
    """Backward-compatibility check.

    Rules: major must match (structure incompatible); file minor ≤ current minor (new fields must
    not appear in old versions, while default values in the model fill missing fields in old files).
    Returns False to reject publishing.
    """

    def _parts(version: str) -> list[int]:
        try:
            return [int(part) for part in version.split(".")[:3]]
        except ValueError:
            return []

    fv, cv = _parts(file_version), _parts(current_version)
    if not fv or not cv:
        return False
    return fv[0] == cv[0] and fv[1] <= cv[1]

# ISO 8601 UTC + Z, e.g. 2026-08-03T10:00:00Z (fractional seconds allowed)
_UTC_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")


def validate_utc_datetime(value: str) -> str:
    """Strictly validate an ISO 8601 UTC + Z time string."""
    if not isinstance(value, str) or not _UTC_DATETIME_RE.match(value):
        raise ValueError(
            f"time must be ISO 8601 UTC + Z format (e.g. 2026-08-03T10:00:00Z), received: {value!r}"
        )
    return value


#: An ISO 8601 UTC + Z timestamp string.
#:
#: The ``WithJsonSchema`` annotation is what makes the constraint *visible* to
#: ``scripts/gen_ts_contracts.py``. An ``AfterValidator`` contributes nothing to
#: ``model_json_schema()``, so without it a timestamp is indistinguishable from any other
#: string and the emitter would have to special-case a Python type name it cannot see.
#: Declaring the format here keeps the contract self-describing: the generated Zod says
#: ``utcDateTime`` because the schema says ``format: date-time``, not because the generator
#: recognised a variable called ``UTCDateTime``.
UTCDateTime = Annotated[
    str,
    AfterValidator(validate_utc_datetime),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]


class ContractModel(BaseModel):
    """Data contract base class.

    Hard constraints (architecture §3.1/§8.3):
    - extra="forbid": no implicit fields (isomorphic to JSON Schema additionalProperties=false)
    - allow_inf_nan=False: rejects NaN/Infinity (applies to all float fields)
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)

    @classmethod
    def parse_finite(cls, value: Any) -> "ContractModel":
        """Convenience entry point: parse and ensure NaN/Infinity are rejected (for tests and pipeline reuse)."""
        return cls.model_validate(value)


class ProviderProvenance(ContractModel):
    """Which provider actually served the dataset (#65, ADR 0004).

    The resolved provider (not the candidate list), whether that was a fallback, and whether
    the value came from the last-good cache. Cache replay is deliberately partial until #66:
    the cache entry does not record the originating provider, so `provider` is "last-good".
    """

    provider: str = Field(min_length=1, description='resolved provider name; "last-good" for cache replay')
    used_fallback: bool = False
    from_cache: bool = False


class FreshnessReason(ContractModel):
    """Why a dataset carries the freshness status it carries (#89).

    Replaces the free-text ``reason`` string that produced eight datasets all saying the
    literal word "degraded".

    ``code`` is machine-readable and drawn from the closed :data:`ReasonCode` vocabulary; the
    UI translates it. ``detail`` is human-readable **English only** and is deliberately not
    translated: its audience is the operator and the next agent, and keeping it monolingual
    is what makes the translated surface finite. ``detail`` is also the only field here that
    can ever carry provider text, so it is the sole input to the redactor (#92).
    """

    code: ReasonCode
    detail: str = Field(default="", max_length=200)


class BaseEnvelope(ContractModel):
    """Global data envelope (architecture §3.1).

    payload is the business data; each dataset model overrides the payload type in a subclass
    for strong validation (e.g. MacroEnvelope(payload: MacroDataset)).
    """

    generated_at: UTCDateTime
    schema_version: str = Field(min_length=1, description='semantic version, e.g. "1.0.0"')
    source: str | list[str]
    source_updated_at: UTCDateTime | None = None
    freshness_status: FreshnessStatus
    data_quality: float = Field(ge=0.0, le=1.0, description="data quality 0-1")
    provenance: ProviderProvenance
    payload: dict[str, Any]


def ensure_no_nan_inf(value: float) -> float:
    """Defensive check (for explicit calls; the normal path is intercepted by allow_inf_nan=False)."""
    if value is not None and isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("value must not be NaN/Infinity")
    return value


class AssembledDataset(NamedTuple):
    """An envelope plus the freshness reason produced with it.

    The envelope deliberately gains no ``reason`` field — that would bump ``SCHEMA_VERSION``
    across 33 models and every fixture to publish a diagnostic the data layer does not need.
    The reason travels beside the envelope to the caller, which writes it to
    ``metadata/freshness.json``: one author, two destinations, no duplication.
    """

    envelope: BaseEnvelope
    reason: FreshnessReason


def assemble_dataset(
    model: type[BaseEnvelope],
    payload: Any,
    *,
    dataset: str,
    degraded: bool,
    provider: str,
    used_fallback: bool = False,
    from_cache: bool = False,
    data_quality: float = 1.0,
    generated_at: str | None = None,
    source_updated_at: str | None = None,
    now: datetime | None = None,
    row_count: int | None = None,
    error_code: str | None = None,
    detail: str = "",
) -> AssembledDataset:
    """The single envelope assembly path (#64/#65).

    Collectors no longer assign ``freshness_status``; they return payloads and the provider
    outcome. This helper computes the status with
    :func:`pipeline.validation.freshness.finalize_freshness` — the only producer — and builds
    the envelope. ``provider`` is the resolved provider that actually served the dataset (#65,
    ADR 0004): it becomes the envelope's ``source`` (the answering provider, not the candidate
    list) and the provenance descriptor. ``now`` is the clock used for the time-based freshness
    determination (the test seam for a fixed clock).

    ``row_count`` is what makes ``empty`` reachable and enforces the invariant that ``fresh``
    requires a non-empty payload (#89). Pass ``None`` for derived datasets that have no
    meaningful row cardinality (``risk``, ``dashboard``), which skips the emptiness check
    rather than silently treating them as empty.

    The verdict's reason is returned to the caller via :func:`freshness_reason_of`, not stored
    on the envelope: the envelope describes the data and its provenance, while the operator
    diagnostic belongs in ``metadata/freshness.json``, which is what the Status page reads.
    """
    # Imported lazily: `pipeline.validation` imports `pipeline.schemas` at package import time,
    # so a module-level import here would be circular.
    from pipeline.utils import now_utc
    from pipeline.validation.freshness import finalize_freshness

    generated_at = generated_at or now_utc()
    source_updated_at = source_updated_at or generated_at
    verdict = finalize_freshness(
        dataset,
        generated_at,
        degraded,
        now=now,
        row_count=row_count,
        error_code=error_code,
        detail=detail,
        used_fallback=used_fallback,
        from_cache=from_cache,
    )
    env = model(
        generated_at=generated_at,
        schema_version=SCHEMA_VERSION,
        source=provider,
        source_updated_at=source_updated_at,
        freshness_status=verdict.status,
        data_quality=data_quality,
        provenance=ProviderProvenance(
            provider=provider,
            used_fallback=used_fallback,
            from_cache=from_cache,
        ),
        payload=payload,
    )
    return AssembledDataset(envelope=env, reason=verdict.reason)


def assemble_envelope(*args: Any, **kwargs: Any) -> BaseEnvelope:
    """Backward-compatible wrapper: :func:`assemble_dataset` without the reason.

    Callers that write ``metadata/freshness.json`` want :func:`assemble_dataset`; callers that
    only need the envelope (tests, the fact-layer rebuild) can keep using this.
    """
    return assemble_dataset(*args, **kwargs).envelope
