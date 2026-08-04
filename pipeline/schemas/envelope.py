"""Global data Envelope (architecture §3.1).

All dataset files must be wrapped in BaseEnvelope; freshness_status is determined uniformly by
the pipeline (not trusting Provider self-reporting, architecture §8.4). This module also provides
the contract base classes and shared primitives:
- ContractModel: no implicit fields + rejects NaN/Infinity (three-artifact hard constraint, architecture §3.1)
- UTCDateTime: strict ISO 8601 UTC + Z validation
- FreshnessStatus: five-state enum
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

FreshnessStatus = Literal["fresh", "delayed", "stale", "missing", "degraded"]

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


UTCDateTime = Annotated[str, AfterValidator(validate_utc_datetime)]


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


def assemble_envelope(
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
) -> BaseEnvelope:
    """The single envelope assembly path (#64/#65).

    Collectors no longer assign ``freshness_status``; they return payloads and the provider
    outcome. This helper computes the status with
    :func:`pipeline.validation.freshness.finalize_freshness` — the only producer — and builds
    the envelope. ``provider`` is the resolved provider that actually served the dataset (#65,
    ADR 0004): it becomes the envelope's ``source`` (the answering provider, not the candidate
    list) and the provenance descriptor. ``now`` is the clock used for the time-based freshness
    determination (the test seam for a fixed clock).
    """
    # Imported lazily: `pipeline.validation` imports `pipeline.schemas` at package import time,
    # so a module-level import here would be circular.
    from pipeline.utils import now_utc
    from pipeline.validation.freshness import finalize_freshness

    generated_at = generated_at or now_utc()
    source_updated_at = source_updated_at or generated_at
    status = finalize_freshness(dataset, generated_at, degraded, now=now)
    return model(
        generated_at=generated_at,
        schema_version=SCHEMA_VERSION,
        source=provider,
        source_updated_at=source_updated_at,
        freshness_status=status,
        data_quality=data_quality,
        provenance=ProviderProvenance(
            provider=provider,
            used_fallback=used_fallback,
            from_cache=from_cache,
        ),
        payload=payload,
    )
