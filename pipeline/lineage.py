"""Lineage primitives for deterministic published data and AI brief inputs.

The fact layer is published independently from the AI brief. A brief therefore needs an
explicit reference to the exact fact generation it read; timestamps alone cannot prove that
relationship because two runs can overlap or be published out of order.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

FACT_GENERATION_ID_PREFIX = "sha256:"
FACT_GENERATION_ID_LENGTH = len(FACT_GENERATION_ID_PREFIX) + 64


def fact_generation_id(facts: Any) -> str:
    """Return the deterministic identity of a fact-layer document.

    ``generated_at`` is publication metadata and is deliberately excluded so rebuilding an
    unchanged fact layer does not create a new identity. ``generation_id`` is excluded to avoid
    hashing the identity into itself. All observed facts, evidence, freshness inputs, and schema
    version remain part of the digest.

    The function accepts both a Pydantic model and a mapping: the builder calculates the identity
    immediately before Pydantic validates and publishes the completed ``FactLayer`` model.
    """
    payload = _json_ready(facts.model_dump(mode="json") if hasattr(facts, "model_dump") else facts)
    if not isinstance(payload, Mapping):
        raise TypeError("facts must be a mapping or a model_dump()-compatible object")
    payload = dict(payload)
    payload.pop("generated_at", None)
    payload.pop("generation_id", None)
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{FACT_GENERATION_ID_PREFIX}{hashlib.sha256(canonical).hexdigest()}"


def _json_ready(value: Any) -> Any:
    """Convert Pydantic models in an in-memory builder payload into JSON values."""
    if hasattr(value, "model_dump"):
        return _json_ready(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    return value


def is_valid_fact_generation_id(value: str | None) -> bool:
    """Return whether ``value`` has the canonical fact-generation identity shape."""
    if not isinstance(value, str) or len(value) != FACT_GENERATION_ID_LENGTH:
        return False
    if not value.startswith(FACT_GENERATION_ID_PREFIX):
        return False
    return all(char in "0123456789abcdef" for char in value[len(FACT_GENERATION_ID_PREFIX) :])
