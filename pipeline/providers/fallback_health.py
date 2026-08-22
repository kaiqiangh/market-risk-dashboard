"""Fallback-provider liveness (#100 DoD: "a fallback nobody tests is not a fallback").

Stooq sat dead for an unknown length of time because the fallback path only runs during an
outage — the `quotes` domain had no working fallback and nothing noticed. This module
gives every fallback provider a standing liveness check: build the real registry, call
each fallback's ``health()``, and report. Wired into a scheduled CI workflow
(.github/workflows/fallback-health.yml).

Three outcomes per fallback:

- ``ok`` — health() answered healthy.
- ``dead`` — health() answered unhealthy (or raised). Fails the check.
- ``skipped`` — the provider needs a credential the runner does not have (a falsy
  ``api_key`` attribute). Cannot be verified here — a skipped fallback never fails the
  job, and its real liveness is exercised by the daily pipeline run (key-gated providers
  like FMP are called every run), which is precisely the gap this check exists to close
  for fallbacks that never run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pipeline.providers.base import BaseProvider, ProviderHealth

ProbeStatus = Literal["ok", "dead", "skipped"]


@dataclass
class FallbackProbe:
    """One fallback's liveness result."""

    domain: str
    provider: str
    priority: int
    status: ProbeStatus
    health: ProviderHealth | None = None
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def error(self) -> str | None:
        if self.health is not None:
            return self.health.error
        return self.note


@dataclass
class FallbackCheckResult:
    probes: list[FallbackProbe] = field(default_factory=list)

    @property
    def dead(self) -> list[FallbackProbe]:
        return [p for p in self.probes if p.status == "dead"]


def fallback_providers(providers: list[BaseProvider]) -> list[BaseProvider]:
    """Providers that are NOT the primary rung of their domain (priority != domain min).

    Priority is the registry's single effective ordering signal (`kind` labels were
    removed from config with #100 — two signals for one role was exactly the drift the
    ticket's C-3 was about).
    """
    by_domain: dict[str, list[BaseProvider]] = {}
    for provider in providers:
        by_domain.setdefault(provider.domain, []).append(provider)
    fallbacks: list[BaseProvider] = []
    for _domain, domain_providers in by_domain.items():
        min_priority = min(p.priority for p in domain_providers)
        fallbacks.extend(p for p in domain_providers if p.priority > min_priority)
    return fallbacks


def check_fallbacks(providers: list[BaseProvider]) -> FallbackCheckResult:
    """Probe every fallback provider's ``health()`` and collect the results."""
    result = FallbackCheckResult()
    for provider in fallback_providers(providers):
        # A credential-gated fallback with no credential cannot be verified — SKIPPED,
        # never failed (a permanently red scheduled job becomes ignored noise, which is
        # the exact failure mode #100 exists to prevent). Key-gated providers are still
        # exercised by the daily pipeline run.
        if getattr(provider, "requires_api_key", False) and not getattr(provider, "api_key", None):
            result.probes.append(
                FallbackProbe(
                    domain=provider.domain,
                    provider=provider.name,
                    priority=provider.priority,
                    status="skipped",
                    note="missing api key (SKIPPED — verified by the daily pipeline run)",
                )
            )
            continue
        try:
            health = provider.health()
            result.probes.append(
                FallbackProbe(
                    domain=provider.domain,
                    provider=provider.name,
                    priority=provider.priority,
                    status="ok" if health.ok else "dead",
                    health=health,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a crashing health() is a dead fallback
            result.probes.append(
                FallbackProbe(
                    domain=provider.domain,
                    provider=provider.name,
                    priority=provider.priority,
                    status="dead",
                    note=f"{type(exc).__name__}: {exc}",
                )
            )
    return result


def render_check(result: FallbackCheckResult) -> str:
    """Human-readable table for the script's stdout."""
    lines = ["domain     provider          priority  status   latency   detail"]
    for p in sorted(result.probes, key=lambda x: (x.domain, x.priority)):
        latency = f"{p.health.latency_ms:.0f}ms" if p.health is not None and p.health.latency_ms is not None else ""
        lines.append(
            f"{p.domain:<10s} {p.provider:<16s} {p.priority:<8d} "
            f"{p.status.upper():<7s} {latency:<8s} {str(p.error or '')[:60]}"
        )
    lines.append("")
    skipped = sum(1 for p in result.probes if p.status == "skipped")
    lines.append(f"fallbacks checked: {len(result.probes)} | dead: {len(result.dead)} | skipped (no key): {skipped}")
    return "\n".join(lines)
