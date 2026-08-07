"""Contracts for the two published metadata documents (#89).

``metadata/freshness.json`` and ``metadata/sources.json`` are the only published files that
had no model. That is precisely why they were able to contradict each other for so long:
nothing validated them on the way out, and the frontend parsed them with hand-written Zod that
drifted independently. They are now modelled here, generated into TypeScript alongside every
other contract, and validated by :class:`~pipeline.storage.outcomes.RunOutcomes` at write time.

The two documents are deliberately *not* wrapped in ``BaseEnvelope``: an envelope describes a
dataset's provenance and freshness, and these files **are** the freshness record. Wrapping the
freshness report in a freshness envelope would be circular.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from .envelope import ContractModel, FreshnessReason, FreshnessStatus, UTCDateTime

#: Schema version of the metadata documents. Tracked separately from ``SCHEMA_VERSION``
#: (the dataset contract version) because the two evolve independently.
METADATA_SCHEMA_VERSION = "1.1.0"


class DatasetFreshness(ContractModel):
    """One dataset's entry in ``metadata/freshness.json``.

    Every registered dataset appears on every run — including the ones that failed. An absent
    key used to mean "healthy, nothing to report" by accident; it now cannot happen, because
    the projection iterates the registry rather than the datasets that happened to succeed.
    """

    status: FreshnessStatus
    reason: FreshnessReason
    updated_at: UTCDateTime


class FreshnessDocument(ContractModel):
    """``metadata/freshness.json`` — the per-dataset freshness record."""

    schema_version: str = Field(min_length=1)
    updated_at: UTCDateTime
    datasets: dict[str, DatasetFreshness] = Field(default_factory=dict)


class DomainStatus(ContractModel):
    """One provider domain's entry in ``metadata/sources.json``.

    ``degraded`` is derived from the outcomes of the datasets this domain serves, never set
    independently — see :meth:`~pipeline.storage.outcomes.RunOutcomes.sources_projection`.

    Unlike every other contract in this package this model permits extra fields. Provider
    metadata is provider-specific and additive (``sources`` for the RSS fan-out, ``error`` for
    a failed call, cache diagnostics), and forbidding it would mean either dropping real
    operational detail on the floor or bumping the schema every time a provider learns to
    report something new. The *derived* fields below are the contract; the rest is passthrough.
    """

    model_config = ConfigDict(extra="allow", allow_inf_nan=False, validate_assignment=True)

    degraded: bool = False
    status: FreshnessStatus = "missing"
    # Required, deliberately: a domain health entry whose reason can be defaulted away is how
    # eight datasets ended up reporting the literal word "degraded" and nothing else.
    reason: FreshnessReason
    datasets: list[str] = Field(
        default_factory=list, description="canonical dataset keys this domain serves"
    )
    provider: str | None = Field(default=None, description="resolved provider, when known")


class SourcesDocument(ContractModel):
    """``metadata/sources.json`` — the per-provider-domain health record."""

    schema_version: str = Field(min_length=1)
    updated_at: UTCDateTime
    domains: dict[str, DomainStatus] = Field(default_factory=dict)
