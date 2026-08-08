"""The per-run dataset outcome record (#89).

``metadata/freshness.json`` and ``metadata/sources.json`` used to be assembled independently:
the first incrementally, keyed by ten dataset names, via a read-modify-write on every dataset;
the second in one shot at the end of the run, keyed by five provider domains. No mapping
between the two key spaces existed anywhere. The predictable result was that they contradicted
each other — ``calendar`` was ``fresh`` in one and ``degraded: true`` in the other, while
``crypto`` and ``macro`` said the opposite pair.

Both files are now **projections of this one record**, joined through
``pipeline/schemas/registry.py``'s dataset↔domain mapping. Two views of one truth cannot
disagree, and a CI check asserts they still agree on ``degraded`` for every key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.schemas import registry
from pipeline.schemas.envelope import STATUS_RANK, FreshnessReason, FreshnessStatus
from pipeline.schemas.metadata import (
    METADATA_SCHEMA_VERSION,
    DatasetFreshness,
    DomainStatus,
    FreshnessDocument,
    ProviderResolution,
    SourcesDocument,
)
from pipeline.utils import now_utc

#: Statuses that mean "this dataset is not carrying trustworthy, current data".
_UNHEALTHY: frozenset[str] = frozenset({"degraded", "missing", "stale"})


@dataclass(frozen=True)
class DatasetOutcome:
    """What happened to one dataset during one run."""

    key: str
    status: FreshnessStatus
    reason: FreshnessReason
    provider: str | None = None
    used_fallback: bool = False
    from_cache: bool = False
    updated_at: str = ""

    @property
    def degraded(self) -> bool:
        return self.status in _UNHEALTHY


class RunOutcomes:
    """Collects dataset outcomes during a run and renders both metadata files at the end.

    ``scope`` is the set of dataset keys this run intends to produce. It matters because a
    partial run must not lie about the datasets it never intended to touch: a ``--news-only``
    run does not invalidate this morning's equities data, so out-of-scope datasets carry their
    previous entry forward rather than being overwritten with ``not_collected_this_run``.
    In-scope datasets that produced no outcome *are* marked ``missing`` — that is a collector
    that exploded, and silence there is exactly what let eight datasets sit unnoticed.
    """

    def __init__(self, scope: set[str] | None = None) -> None:
        self.scope: set[str] = set(scope or registry.CANONICAL_KEYS)
        self._outcomes: dict[str, DatasetOutcome] = {}

    def record(
        self,
        key: str,
        status: FreshnessStatus,
        reason: FreshnessReason,
        *,
        provider: str | None = None,
        used_fallback: bool = False,
        from_cache: bool = False,
    ) -> None:
        """Record the outcome for one dataset. Raises on an unregistered key."""
        registry.require(key)
        self._outcomes[key] = DatasetOutcome(
            key=key,
            status=status,
            reason=reason,
            provider=provider,
            used_fallback=used_fallback,
            from_cache=from_cache,
            updated_at=now_utc(),
        )

    def record_envelope(self, key: str, env: Any, reason: FreshnessReason) -> None:
        """Record from an assembled envelope, lifting provenance off it."""
        prov = getattr(env, "provenance", None)
        self.record(
            key,
            env.freshness_status,
            reason,
            provider=getattr(prov, "provider", None),
            used_fallback=bool(getattr(prov, "used_fallback", False)),
            from_cache=bool(getattr(prov, "from_cache", False)),
        )

    def get(self, key: str) -> DatasetOutcome | None:
        return self._outcomes.get(key)

    def freshness_projection(self, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        """Render ``metadata/freshness.json``: every registered dataset, always present.

        ``previous`` is the file as it stood before this run, used to carry forward datasets
        this run did not attempt.
        """
        prior = dict((previous or {}).get("datasets", {}))
        datasets: dict[str, DatasetFreshness] = {}

        for key in registry.CANONICAL_KEYS:
            outcome = self._outcomes.get(key)
            if outcome is not None:
                datasets[key] = DatasetFreshness(
                    status=outcome.status,
                    reason=outcome.reason,
                    updated_at=outcome.updated_at,
                )
                continue

            if key not in self.scope:
                # Untouched by this run: carrying the old entry forward is honest, whereas
                # overwriting it would make every partial run look catastrophic.
                carried = _carry_forward(prior.get(key))
                if carried is not None:
                    datasets[key] = carried
                    continue

            datasets[key] = DatasetFreshness(
                status="missing",
                reason=FreshnessReason(
                    code="not_collected_this_run",
                    detail=(
                        "in scope for this run but no outcome was recorded"
                        if key in self.scope
                        else "never produced by any run so far"
                    ),
                ),
                updated_at=now_utc(),
            )

        return FreshnessDocument(
            schema_version=METADATA_SCHEMA_VERSION,
            updated_at=now_utc(),
            datasets=datasets,
        ).model_dump(mode="json")

    def sources_projection(self, provider_status: dict[str, Any]) -> dict[str, Any]:
        """Render ``metadata/sources.json``: provider status joined to dataset outcomes.

        ``degraded`` is **derived** from the outcomes of the datasets a domain serves, never set
        independently. That derivation is the whole point: it is structurally impossible for
        this file to claim a domain is healthy while ``freshness.json`` calls its dataset
        degraded, because both answers now come from the same place.
        """
        domains: dict[str, DomainStatus] = {}
        for domain, keys in registry.DOMAIN_DATASETS.items():
            outcomes = [o for o in (self._outcomes.get(k) for k in keys) if o is not None]
            entry: dict[str, Any] = dict(provider_status.get(domain) or {})
            entry["datasets"] = list(keys)
            resolutions = _provider_resolutions(keys, outcomes, entry)
            entry["providers"] = [resolution.model_dump(mode="json") for resolution in resolutions]
            entry["provider"] = _provider_summary(resolutions, entry.get("provider"))
            if outcomes:
                worst = max(outcomes, key=lambda o: _rank(o.status))
                entry["degraded"] = any(o.degraded for o in outcomes)
                entry["status"] = worst.status
                entry["reason"] = worst.reason
            else:
                entry.setdefault("degraded", False)
                entry["status"] = "missing"
                entry["reason"] = FreshnessReason(code="not_collected_this_run", detail="")
            domains[domain] = DomainStatus.model_validate(entry)

        # Domains reported by collectors that serve no registered dataset (for example RSS
        # source detail) are retained, but internal market routing domains are not. The latter
        # are implementation details of the canonical ``market`` domain and must not appear as
        # competing top-level status rows (#136).
        internal_domains = {"quotes", "a_share"}
        for domain, value in provider_status.items():
            if domain in domains or domain in internal_domains:
                continue
            unmapped = dict(value or {})
            unmapped.setdefault("degraded", False)
            unmapped["datasets"] = []
            resolutions = _provider_resolutions((), [], unmapped)
            unmapped["providers"] = [resolution.model_dump(mode="json") for resolution in resolutions]
            unmapped["provider"] = _provider_summary(resolutions, unmapped.get("provider"))
            unmapped["status"] = "missing"
            unmapped["reason"] = FreshnessReason(
                code="not_collected_this_run",
                detail=f"provider domain {domain!r} serves no registered dataset",
            )
            domains[domain] = DomainStatus.model_validate(unmapped)

        return SourcesDocument(
            schema_version=METADATA_SCHEMA_VERSION,
            updated_at=now_utc(),
            domains=domains,
        ).model_dump(mode="json")


def _provider_resolutions(
    keys: tuple[str, ...], outcomes: list[DatasetOutcome], entry: dict[str, Any]
) -> list[ProviderResolution]:
    """Group successful dataset outcomes into deterministic provider resolutions."""
    explicit = _explicit_provider_resolutions(keys, entry)
    if explicit:
        return explicit

    grouped: dict[tuple[str, bool, bool], list[str]] = {}
    for key in keys:
        outcome = next((item for item in outcomes if item.key == key), None)
        if outcome is None or not outcome.provider or outcome.provider == "unavailable":
            continue
        group = (str(outcome.provider), outcome.used_fallback, outcome.from_cache)
        grouped.setdefault(group, []).append(key)

    if not grouped:
        provider = entry.get("provider")
        if provider and str(provider) != "unavailable":
            grouped[(str(provider), bool(entry.get("used_fallback")), bool(entry.get("from_cache")))] = list(keys)

    return [
        ProviderResolution(
            provider=provider,
            datasets=list(dict.fromkeys(datasets)),
            used_fallback=used_fallback,
            from_cache=from_cache,
        )
        for (provider, used_fallback, from_cache), datasets in sorted(grouped.items())
    ]


def _explicit_provider_resolutions(
    keys: tuple[str, ...], entry: dict[str, Any]
) -> list[ProviderResolution]:
    """Read provider metadata explicitly reported for this status domain."""
    grouped: dict[tuple[str, bool, bool], list[str]] = {}
    raw = entry.get("providers")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                resolution = ProviderResolution.model_validate(item)
            except Exception:  # noqa: BLE001 - malformed additive detail is ignored
                continue
            if resolution.provider != "unavailable":
                grouped[(resolution.provider, resolution.used_fallback, resolution.from_cache)] = list(
                    resolution.datasets
                )

    if not grouped:
        provider = entry.get("provider")
        if provider and str(provider) != "unavailable":
            grouped[(str(provider), bool(entry.get("used_fallback")), bool(entry.get("from_cache")))] = list(keys)

    return [
        ProviderResolution(
            provider=provider,
            datasets=list(dict.fromkeys(datasets)),
            used_fallback=used_fallback,
            from_cache=from_cache,
        )
        for (provider, used_fallback, from_cache), datasets in sorted(grouped.items())
    ]


def _provider_summary(resolutions: list[ProviderResolution], fallback: Any = None) -> str:
    """Return a stable human-readable provider summary, never null for a domain."""
    names = sorted({resolution.provider for resolution in resolutions})
    if names:
        return ", ".join(names)
    if fallback and str(fallback) != "unavailable":
        return str(fallback)
    return "unavailable"


def _carry_forward(entry: Any) -> DatasetFreshness | None:
    """Validate a previous ``freshness.json`` entry so it can be carried into this run.

    Returns ``None`` when the entry is absent or predates the ``{code, detail}`` reason — a
    partial run must not crash on a file written by an older pipeline, and it must not launder
    an unparseable entry forward either. Falling back to ``missing`` is the honest answer:
    we genuinely do not know the state of a dataset we did not collect and cannot read.
    """
    if not isinstance(entry, dict):
        return None
    try:
        return DatasetFreshness.model_validate(entry)
    except Exception:  # noqa: BLE001 - any validation failure means "unusable", not "fatal"
        return None


def _rank(status: str) -> int:
    # Severity ordering lives once, in pipeline.schemas.envelope.STATUS_RANK (shared with
    # validation/freshness.py). An unknown status outranks everything (len+1) rather than
    # being silently ranked as fresh — the fail-loudly stance of registry.require.
    return STATUS_RANK.get(str(status), len(STATUS_RANK) + 1)
