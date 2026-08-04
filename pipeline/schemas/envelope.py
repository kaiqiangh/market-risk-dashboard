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
    payload: dict[str, Any]


def ensure_no_nan_inf(value: float) -> float:
    """Defensive check (for explicit calls; the normal path is intercepted by allow_inf_nan=False)."""
    if value is not None and isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError("value must not be NaN/Infinity")
    return value
