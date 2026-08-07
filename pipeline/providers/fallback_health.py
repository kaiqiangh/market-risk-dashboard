"""Fallback-provider liveness (#100 DoD: "a fallback nobody tests is not a fallback").

Stooq sat dead for an unknown length of time because the fallback path only runs during an
outage — the `quotes` domain had no working fallback and nothing noticed. This module
gives every fallback provider a standing liveness check: build the real registry, call
each fallback's ``health()``, and report. Wired into a scheduled CI workflow
(.github/workflows/fallback-health.yml) so a dead fallback fails loudly instead of hiding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.providers.base import BaseProvider


@dataclass
class FallbackProbe:
    """One fallback's liveness result."""

    domain: str
    provider: str
    priority: int
    ok: bool
    error: str | None = None
    latency_ms: float | None = None


@dataclass
class FallbackCheckResult:
    probes: list[FallbackProbe] = field(default_factory=list)

    @property
    def dead(self) -> list[FallbackProbe]:
        return [p for p in self.probes if not p.ok]


def fallback_providers(providers: list[BaseProvider]) -> list[BaseProvider]:
    """Providers that are NOT the primary rung of their domain (priority != domain min).

    `kind` in config is descriptive; priority is the effective order — a provider whose
    priority is above the domain minimum is a fallback by construction.
    """
    by_domain: dict[str, list[BaseProvider]] = {}
    for provider in providers:
        by_domain.setdefault(provider.domain, []).append(provider)
    fallbacks: list[BaseProvider] = []
    for domain, domain_providers in by_domain.items():
        min_priority = min(p.priority for p in domain_providers)
        fallbacks.extend(p for p in domain_providers if p.priority > min_priority)
    return fallbacks


def check_fallbacks(providers: list[BaseProvider]) -> FallbackCheckResult:
    """Probe every fallback provider's ``health()`` and collect the results."""
    result = FallbackCheckResult()
    for provider in fallback_providers(providers):
        try:
            health = provider.health()
            result.probes.append(
                FallbackProbe(
                    domain=provider.domain,
                    provider=provider.name,
                    priority=provider.priority,
                    ok=bool(health.ok),
                    error=health.error,
                    latency_ms=health.latency_ms,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a crashing health() is a dead fallback
            result.probes.append(
                FallbackProbe(
                    domain=provider.domain,
                    provider=provider.name,
                    priority=provider.priority,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    return result


def render_check(result: FallbackCheckResult) -> str:
    """Human-readable table for the script's stdout."""
    lines = ["domain     provider          priority  ok    latency   error"]
    for p in sorted(result.probes, key=lambda x: (x.domain, x.priority)):
        lines.append(
            f"{p.domain:<10s} {p.provider:<16s} {p.priority:<8d} "
            f"{'YES' if p.ok else 'NO ':3s} {str(p.latency_ms or ''):<8s} {str(p.error or '')[:60]}"
        )
    lines.append("")
    lines.append(f"fallbacks checked: {len(result.probes)} | dead: {len(result.dead)}")
    return "\n".join(lines)
