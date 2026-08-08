#!/usr/bin/env python3
"""Generate the frontend contract layer from the pydantic models (#88, #101).

The Python and TypeScript contracts used to be two hand-maintained descriptions of the same
JSON, kept in agreement by review discipline. They drifted, as they always do: the frontend's
``FreshnessStatus`` was missing a state, ``expected_interval_minutes`` existed in three places
with two different values for ``risk``, and ``news.zh-translations.json`` had a Zod schema but
no registration anywhere. This script makes the TypeScript a *derivative* of the Python, so
the only way to change the contract is to change the model.

Outputs (all under ``src/schemas/generated/``, all checked in):

``contracts.ts``    Zod schemas + inferred types for every published model.
``constants.json``  The values the runtime needs that are not schemas: the freshness and
                    reason vocabularies, the dataset registry, and the expected update
                    intervals from ``config/sources.yaml``.
``index.ts``        Barrel re-export.

Design notes
------------

**Unknown constructs raise.** Every emitter branch ends in :class:`UnsupportedSchema` rather
than a fallback to ``z.any()``. A generator that silently degrades is worse than no generator:
it produces a schema that validates nothing while looking like it validates everything, and
nobody notices until production data is wrong. If this script fails, the fix is to teach it
the construct — not to loosen it.

**Generated schemas are passthrough, not strict** (decision #88). The pydantic models keep
``extra="forbid"`` because the pipeline is the *producer* and must not publish fields it did
not mean to. The frontend is the *consumer*, and a consumer that hard-fails a whole page
because the pipeline added a field is a self-inflicted outage. Unknown fields are reported
once per dataset per session by ``src/lib/api.ts`` instead.

**Defaults become ``.default()``, not ``.optional()``.** A pydantic field with a default is
absent-tolerant but never ``undefined`` after parsing, and ``.default()`` is the Zod
construct with exactly those semantics. Using ``.optional()`` would leak ``| undefined`` into
every inferred type and force null-checks the contract says are unnecessary.

Usage::

    python scripts/gen_ts_contracts.py            # write
    python scripts/gen_ts_contracts.py --check    # fail on drift (CI)
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from pydantic.json_schema import models_json_schema  # noqa: E402

import pipeline.schemas  # noqa: E402,F401  (import for the side effect: resolves forward refs)
from pipeline.schemas import registry  # noqa: E402
from pipeline.schemas.envelope import SCHEMA_VERSION, BaseEnvelope  # noqa: E402
from pipeline.schemas.metadata import (  # noqa: E402
    METADATA_SCHEMA_VERSION,
    FreshnessDocument,
    SourcesDocument,
)

OUT_DIR = ROOT / "src" / "schemas" / "generated"
SOURCES_YAML = ROOT / "config" / "sources.yaml"

#: Modules scanned for module-level ``Literal[...]`` aliases. A named alias in Python becomes a
#: named ``z.enum`` in TypeScript; without this the emitter would inline every enum and the
#: frontend would lose ``RiskLevel``, ``MarketRegime`` and friends as importable types.
ENUM_MODULES = (
    "envelope",
    "equities",
    "sectors",
    "crypto",
    "macro",
    "calendar",
    "news",
    "risk",
    "dashboard",
    "factlayer",
    "analysis",
)

#: Root models to generate. The dataset models come from the registry so a new dataset is
#: generated the moment it is registered; the metadata documents and the bare envelope are
#: named explicitly because they are not datasets.
def _root_models() -> list[Any]:
    roots: list[Any] = [BaseEnvelope, FreshnessDocument, SourcesDocument]
    for spec in registry.DATASETS:
        if spec.model not in roots:
            roots.append(spec.model)
    return roots


class UnsupportedSchema(RuntimeError):
    """A JSON Schema construct the emitter does not understand.

    Raised rather than degrading to ``z.any()``. See the module docstring.
    """

    def __init__(self, where: str, node: Any) -> None:
        super().__init__(
            f"unsupported JSON Schema construct at {where}: {json.dumps(node, sort_keys=True)}\n"
            f"Teach scripts/gen_ts_contracts.py this construct; do not loosen it to z.any()."
        )


# ============================================================
# Named enum discovery
# ============================================================


def discover_named_enums() -> dict[tuple[str, ...], str]:
    """Map a literal's exact member tuple to the Python alias name that declares it.

    Keyed on the ordered tuple rather than a set so that two aliases with the same members in
    a different order stay distinct — order is part of the contract for anything that renders
    the vocabulary as a list.
    """
    import importlib

    found: dict[tuple[str, ...], str] = {}
    for mod_name in ENUM_MODULES:
        module = importlib.import_module(f"pipeline.schemas.{mod_name}")
        for attr, value in vars(module).items():
            if attr.startswith("_") or get_origin(value) is not Literal:
                continue
            args = get_args(value)
            if not args or not all(isinstance(a, str) for a in args):
                continue
            key = tuple(args)
            # First declaration wins, so a re-export cannot rename an alias.
            found.setdefault(key, attr)
    return found


# ============================================================
# Emitter
# ============================================================


class Emitter:
    def __init__(self, defs: dict[str, Any], named_enums: dict[tuple[str, ...], str]) -> None:
        self.defs = defs
        self.named_enums = named_enums
        #: enum aliases actually reachable from the models, plus every declared alias — the
        #: frontend wants ``ReasonCode`` even though no published field is typed as one.
        self.emitted_enums: dict[str, tuple[str, ...]] = {
            name: members for members, name in named_enums.items()
        }

    # -- helpers ------------------------------------------------------

    @staticmethod
    def _numeric_bounds(node: dict[str, Any]) -> str:
        out = ""
        if "minimum" in node:
            out += f".min({_num(node['minimum'])})"
        if "exclusiveMinimum" in node:
            out += f".gt({_num(node['exclusiveMinimum'])})"
        if "maximum" in node:
            out += f".max({_num(node['maximum'])})"
        if "exclusiveMaximum" in node:
            out += f".lt({_num(node['exclusiveMaximum'])})"
        return out

    def _enum(self, members: list[str], where: str) -> str:
        if not all(isinstance(m, str) for m in members):
            raise UnsupportedSchema(where, {"enum": members})
        named = self.named_enums.get(tuple(members))
        if named:
            return named
        inner = ", ".join(json.dumps(m) for m in members)
        return f"z.enum([{inner}])"

    # -- main dispatch ------------------------------------------------

    def emit(self, node: Any, where: str) -> str:
        if not isinstance(node, dict):
            raise UnsupportedSchema(where, node)

        if "$ref" in node:
            ref = node["$ref"]
            prefix = "#/$defs/"
            if not ref.startswith(prefix):
                raise UnsupportedSchema(where, node)
            return ref[len(prefix) :]

        if "anyOf" in node:
            return self._any_of(node["anyOf"], where)

        if "enum" in node:
            return self._enum(list(node["enum"]), where)

        jtype = node.get("type")

        if jtype == "string":
            if node.get("format") == "date-time":
                # Bounds on a timestamp would be meaningless; reject rather than drop them.
                if {"minLength", "maxLength"} & node.keys():
                    raise UnsupportedSchema(where, node)
                return "utcDateTime"
            if node.get("format"):
                raise UnsupportedSchema(where, node)
            out = "z.string()"
            if "minLength" in node:
                out += f".min({int(node['minLength'])})"
            if "maxLength" in node:
                out += f".max({int(node['maxLength'])})"
            if "pattern" in node:
                out += f".regex(new RegExp({json.dumps(node['pattern'])}))"
            return out

        if jtype == "number":
            # allow_inf_nan=False on ContractModel applies to every float field, so .finite()
            # is unconditional rather than inferred.
            return "z.number().finite()" + self._numeric_bounds(node)

        if jtype == "integer":
            return "z.number().int()" + self._numeric_bounds(node)

        if jtype == "boolean":
            return "z.boolean()"

        if jtype == "null":
            return "z.null()"

        if jtype == "array":
            items = node.get("items")
            if items is None:
                raise UnsupportedSchema(where, node)
            return f"z.array({self.emit(items, f'{where}[]')})"

        if jtype == "object":
            if "properties" in node:
                # A nested inline object. Every model in this package is a named class, so an
                # inline object means someone used a TypedDict or a raw dict schema.
                raise UnsupportedSchema(where, node)
            extra = node.get("additionalProperties")
            if extra is True or extra is None:
                return "z.record(z.unknown())"
            if extra is False:
                raise UnsupportedSchema(where, node)
            return f"z.record({self.emit(extra, f'{where}{{}}')})"

        raise UnsupportedSchema(where, node)

    def _any_of(self, members: list[Any], where: str) -> str:
        nullable = any(isinstance(m, dict) and m.get("type") == "null" for m in members)
        rest = [m for m in members if not (isinstance(m, dict) and m.get("type") == "null")]
        if not rest:
            raise UnsupportedSchema(where, {"anyOf": members})
        if len(rest) == 1:
            inner = self.emit(rest[0], where)
        else:
            parts = ", ".join(self.emit(m, f"{where}|{i}") for i, m in enumerate(rest))
            inner = f"z.union([{parts}])"
        return f"{inner}.nullable()" if nullable else inner

    # -- object models ------------------------------------------------

    def emit_model(self, name: str, node: dict[str, Any]) -> str:
        props: dict[str, Any] = node.get("properties", {})
        required = set(node.get("required", []))
        lines: list[str] = []
        for field, sub in props.items():
            expr = self.emit(sub, f"{name}.{field}")
            expr += self._default_suffix(name, field, sub, field in required)
            lines.append(f"    {_key(field)}: {expr},")
        body = "\n".join(lines)
        doc = _doc(node.get("description"))
        return f"{doc}export const {name} = z\n  .object({{\n{body}\n  }})\n  .passthrough();"

    def _default_suffix(self, model: str, field: str, sub: dict[str, Any], required: bool) -> str:
        if required:
            return ""
        if "default" in sub:
            return f".default({json.dumps(sub['default'])})"
        # pydantic omits `default` for default_factory fields, but the factory's identity is
        # recoverable from the declared type: a list field defaults to [], a mapping to {}.
        jtype = sub.get("type")
        if jtype == "array":
            return ".default([])"
        if jtype == "object":
            return ".default({})"
        raise UnsupportedSchema(
            f"{model}.{field}",
            {"reason": "optional field with no recoverable default", **sub},
        )


def _num(value: Any) -> str:
    f = float(value)
    return str(int(f)) if f.is_integer() else str(f)


def _key(name: str) -> str:
    return name if name.isidentifier() else json.dumps(name)


def _doc(text: str | None) -> str:
    if not text:
        return ""
    one_line = " ".join(str(text).split())
    return f"/** {one_line} */\n"


# ============================================================
# Ordering
# ============================================================


def dependency_order(defs: dict[str, Any]) -> list[str]:
    """Topologically sort the model definitions so every ``const`` is declared before use."""

    def refs_of(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                found.add(ref[len("#/$defs/") :])
            for value in node.values():
                found |= refs_of(value)
        elif isinstance(node, list):
            for item in node:
                found |= refs_of(item)
        return found

    edges = {name: refs_of(node) & set(defs) for name, node in defs.items()}
    ordered: list[str] = []
    state: dict[str, int] = {}

    def visit(name: str, trail: tuple[str, ...]) -> None:
        mark = state.get(name, 0)
        if mark == 2:
            return
        if mark == 1:
            raise UnsupportedSchema(
                " -> ".join((*trail, name)),
                {"reason": "circular model reference; Zod needs z.lazy() here"},
            )
        state[name] = 1
        for dep in sorted(edges[name]):
            visit(dep, (*trail, name))
        state[name] = 2
        ordered.append(name)

    for name in sorted(defs):
        visit(name, ())
    return ordered


# ============================================================
# Rendering
# ============================================================

HEADER = """// ============================================================================
// GENERATED FILE - DO NOT EDIT
//
// Produced by scripts/gen_ts_contracts.py from the pydantic models in
// pipeline/schemas/. Run `npm run gen:contracts` after changing a model;
// `npm run check:contracts` fails CI when this file is out of date.
//
// Schemas are .passthrough(), not .strict(): the pipeline forbids extra fields
// on the way out, and the frontend tolerates them on the way in so that adding
// a field to a dataset cannot take a page down. Unknown fields are reported by
// src/lib/api.ts.
// ============================================================================
/* eslint-disable */
import { z } from "zod";

/** ISO 8601 UTC + Z timestamp, e.g. 2026-08-03T10:00:00Z. */
export const utcDateTime = z.string().datetime();
"""


def render_contracts(defs: dict[str, Any], emitter: Emitter) -> str:
    chunks: list[str] = [HEADER]

    chunks.append("// ---- Enumerations (Literal aliases in pipeline/schemas/) ----\n")
    for name in sorted(emitter.emitted_enums):
        members = emitter.emitted_enums[name]
        inner = ", ".join(json.dumps(m) for m in members)
        chunks.append(
            f"export const {name} = z.enum([{inner}]);\n"
            f"export type {name} = z.infer<typeof {name}>;\n"
        )

    chunks.append("\n// ---- Models ----\n")
    order = dependency_order(defs)
    for name in order:
        chunks.append(emitter.emit_model(name, defs[name]))
        chunks.append(f"export type {name} = z.infer<typeof {name}>;\n")

    return "\n".join(chunks).rstrip() + "\n"


def render_index(defs: dict[str, Any]) -> str:
    return (
        "// GENERATED FILE - DO NOT EDIT (scripts/gen_ts_contracts.py)\n"
        'export * from "./contracts";\n'
        'export { default as CONTRACT_CONSTANTS } from "./constants.json";\n'
    )


def build_constants(named_enums: dict[tuple[str, ...], str]) -> dict[str, Any]:
    """The non-schema half of the contract: vocabularies, the registry, and the intervals."""
    config = yaml.safe_load(SOURCES_YAML.read_text(encoding="utf-8"))
    expectations = config.get("expectations") or {}

    unregistered = sorted(set(expectations) - set(registry.CANONICAL_KEYS))
    unexpected = sorted(set(registry.CANONICAL_KEYS) - set(expectations))
    if unregistered or unexpected:
        raise SystemExit(
            "config/sources.yaml:expectations and the dataset registry disagree.\n"
            f"  in sources.yaml but not registered: {unregistered}\n"
            f"  registered but missing an interval: {unexpected}"
        )

    by_name = {name: list(members) for members, name in named_enums.items()}

    return {
        "_generated_by": "scripts/gen_ts_contracts.py",
        "schema_version": SCHEMA_VERSION,
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "freshness_status": by_name["FreshnessStatus"],
        "reason_codes": by_name["ReasonCode"],
        "canonical_dataset_keys": list(registry.CANONICAL_KEYS),
        "expected_interval_minutes": {
            key: int(expectations[key]["interval_minutes"]) for key in registry.CANONICAL_KEYS
        },
        "datasets": {
            spec.key: {
                "filenames": list(spec.filenames),
                "enveloped": spec.enveloped,
                "domain": spec.domain,
                "required": spec.required,
                "row_counted": spec.row_counted,
                # Read off the model rather than assumed. scripts/validate-json.mjs used to
                # require schema_version on every self-describing file, which is true of
                # facts.json and analysis.*.json but not of news.zh-translations.json — the
                # kind of near-miss that gets "fixed" by loosening the check for everyone.
                "has_schema_version": "schema_version" in spec.model.model_fields,
            }
            for spec in registry.DATASETS
        },
        "domain_datasets": {d: list(k) for d, k in registry.DOMAIN_DATASETS.items()},
        "non_dataset_suffixes": list(registry.NON_DATASET_SUFFIXES),
    }


# ============================================================
# Entry point
# ============================================================


def generate() -> dict[str, str]:
    named_enums = discover_named_enums()
    _key_map, schemas = models_json_schema(
        [(m, "validation") for m in _root_models()], ref_template="#/$defs/{model}"
    )
    defs: dict[str, Any] = schemas.get("$defs", {})
    emitter = Emitter(defs, named_enums)
    return {
        "contracts.ts": render_contracts(defs, emitter),
        "constants.json": json.dumps(build_constants(named_enums), indent=2) + "\n",
        "index.ts": render_index(defs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if the checked-in output is stale"
    )
    args = parser.parse_args()

    files = generate()

    if args.check:
        stale: list[str] = []
        for name, content in files.items():
            path = OUT_DIR / name
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != content:
                stale.append(name)
                diff = difflib.unified_diff(
                    current.splitlines(keepends=True),
                    content.splitlines(keepends=True),
                    fromfile=f"a/{path.relative_to(ROOT)}",
                    tofile=f"b/{path.relative_to(ROOT)}",
                )
                sys.stdout.writelines(diff)
        if stale:
            print(
                f"\n[gen_ts_contracts] STALE: {', '.join(stale)}\n"
                "Run `npm run gen:contracts` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"[gen_ts_contracts] up to date ({len(files)} files)")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (OUT_DIR / name).write_text(content, encoding="utf-8")
    print(f"[gen_ts_contracts] wrote {len(files)} files to {OUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
