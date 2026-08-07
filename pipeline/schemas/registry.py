"""The canonical dataset registry — one list, one meaning (#88, #89).

Before this module the same knowledge lived in five places that had already drifted apart:

- ``validation/validate_all.py:DATASET_MODELS`` and ``validation/ci_checks.py:ENVELOPE_MODELS``
  (byte-identical copies under different names), plus two copies of ``STANDALONE_MODELS`` and
  a third, differently-keyed ``run.py:_ENVELOPE_MODELS``
- the expected-interval key, where ``risk.json`` mapped to ``"analysis"`` (720 min) in CI but
  read ``expectations.risk`` (480 min) in the envelope, so one file could be ``fresh`` in its
  envelope and ``delayed`` in CI
- the dataset-vs-provider-domain split, which existed nowhere at all: ``freshness.json`` was
  keyed by ten dataset names and ``sources.json`` by five provider domains, with no mapping
  between them — which is precisely why the two files could contradict each other

The canonical key is the dataset's own name and is used *everywhere*: as the
``metadata/freshness.json`` key, as the ``config/sources.yaml:expectations`` key, and as the
argument to :func:`~pipeline.validation.freshness.finalize_freshness`. Filenames are declared
per dataset rather than derived, because two datasets do not follow the stem convention:
``factlayer`` publishes ``facts.json``, and ``analysis`` publishes one file per language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.schemas.analysis import AnalysisDataset
from pipeline.schemas.calendar import CalendarEnvelope
from pipeline.schemas.commodities import CommoditiesEnvelope
from pipeline.schemas.crypto import CryptoEnvelope
from pipeline.schemas.dashboard import DashboardEnvelope
from pipeline.schemas.equities import EquitiesEnvelope
from pipeline.schemas.factlayer import FactLayer
from pipeline.schemas.macro import MacroEnvelope
from pipeline.schemas.news import NewsEnvelope, NewsTranslationsDataset
from pipeline.schemas.risk import RiskEnvelope
from pipeline.schemas.sectors import SectorsEnvelope


@dataclass(frozen=True)
class DatasetSpec:
    """Everything the pipeline, the validators and the metadata writers need about one dataset.

    ``domain`` is the provider domain that serves it, or ``None`` for datasets derived from
    other datasets rather than fetched. It is what lets ``freshness.json`` (keyed by dataset)
    and ``sources.json`` (keyed by domain) be rendered as two projections of one record.

    ``required`` means "a full run must produce this". ``analysis`` and ``news_translations``
    are produced by the AI automations rather than the collection run, so their absence is a
    degraded mode, not a failure.

    ``row_counted`` marks datasets whose payload has a meaningful row cardinality. Derived
    datasets like ``risk`` and ``dashboard`` are always a single object, so asking whether they
    are "empty" is a category error — they pass ``row_count=None`` and skip the check.

    ``row_key`` is the payload field whose length is the row cardinality for ``row_counted``
    datasets (``calendar`` → ``events``, ``news`` → ``items``). It lives here, on the spec,
    because two consumers need it: the producer (``run.py`` computes ``row_count`` from it to
    make ``empty`` reachable) and the re-assertion (``ci_checks.py`` verifies a committed
    ``fresh`` file is not actually empty). Before it was a registry field it was a magic list
    of attribute names in ``run.py`` that did not even mention ``macro``'s row lists, so the
    macro dataset could never be scored empty.
    """

    key: str
    filenames: tuple[str, ...]
    model: Any
    enveloped: bool
    domain: str | None
    required: bool
    row_counted: bool
    row_key: str | None = None


#: The canonical dataset vocabulary. Adding a dataset means adding it here and nowhere else.
#:
#: ``ashare`` is deliberately absent: #97 introduces the model and the collector, and
#: registering a dataset before it can be produced would make every run report it ``missing``.
DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        key="equities",
        filenames=("equities.json",),
        model=EquitiesEnvelope,
        enveloped=True,
        domain="market",
        required=True,
        row_counted=True,
        row_key="assets",
    ),
    DatasetSpec(
        key="sectors",
        filenames=("sectors.json",),
        model=SectorsEnvelope,
        enveloped=True,
        domain="market",
        required=True,
        row_counted=True,
        row_key="sectors",
    ),
    DatasetSpec(
        key="crypto",
        filenames=("crypto.json",),
        model=CryptoEnvelope,
        enveloped=True,
        domain="crypto",
        required=True,
        row_counted=True,
        row_key="assets",
    ),
    DatasetSpec(
        key="commodities",
        filenames=("commodities.json",),
        model=CommoditiesEnvelope,
        enveloped=True,
        domain="market",
        required=True,
        row_counted=True,
        row_key="assets",
    ),
    DatasetSpec(
        key="macro",
        filenames=("macro.json",),
        model=MacroEnvelope,
        enveloped=True,
        domain="macro",
        required=True,
        row_counted=True,
        row_key="rates",
    ),
    DatasetSpec(
        key="calendar",
        filenames=("calendar.json",),
        model=CalendarEnvelope,
        enveloped=True,
        domain="calendar",
        required=True,
        row_counted=True,
        row_key="events",
    ),
    DatasetSpec(
        key="news",
        filenames=("news.json",),
        model=NewsEnvelope,
        enveloped=True,
        domain="news",
        required=True,
        row_counted=True,
        row_key="items",
    ),
    DatasetSpec(
        key="risk",
        filenames=("risk.json",),
        model=RiskEnvelope,
        enveloped=True,
        domain=None,
        required=True,
        row_counted=False,
    ),
    DatasetSpec(
        key="dashboard",
        filenames=("dashboard.json",),
        model=DashboardEnvelope,
        enveloped=True,
        domain=None,
        required=True,
        row_counted=False,
    ),
    DatasetSpec(
        key="factlayer",
        filenames=("facts.json",),
        model=FactLayer,
        enveloped=False,
        domain=None,
        required=True,
        row_counted=False,
    ),
    DatasetSpec(
        key="analysis",
        filenames=("analysis.zh-CN.json", "analysis.en.json"),
        model=AnalysisDataset,
        enveloped=False,
        domain=None,
        required=False,
        row_counted=False,
    ),
    DatasetSpec(
        key="news_translations",
        filenames=("news.zh-translations.json",),
        model=NewsTranslationsDataset,
        enveloped=False,
        domain=None,
        required=False,
        row_counted=False,
    ),
)

BY_KEY: dict[str, DatasetSpec] = {spec.key: spec for spec in DATASETS}

#: published filename → spec. Every file under ``latest/`` must appear here or in
#: :data:`NON_DATASET_FILES`; anything else is a validation **failure**, not a skip (S-4).
BY_FILENAME: dict[str, DatasetSpec] = {
    name: spec for spec in DATASETS for name in spec.filenames
}

#: Files that legitimately live under ``latest/`` without being datasets. Pre-compressed
#: variants are generated by ``scripts/precompress.mjs`` at build time.
NON_DATASET_SUFFIXES: tuple[str, ...] = (".gz", ".br")

CANONICAL_KEYS: tuple[str, ...] = tuple(spec.key for spec in DATASETS)

#: dataset key → provider domain, for the datasets that are actually fetched.
DATASET_DOMAIN: dict[str, str] = {
    spec.key: spec.domain for spec in DATASETS if spec.domain is not None
}

#: Provider domains that serve an existing dataset but are NOT the dataset's canonical
#: domain. #94: economic events are first-class alongside earnings, and the economic
#: provider domain (FRED releases + FOMC) feeds the same ``calendar`` dataset — without
#: this join, ``sources.json`` would stamp the healthy economic domain ``missing`` every
#: run (the E-1 class of misleading metadata this repo has been closing).
EXTRA_DOMAIN_DATASETS: dict[str, tuple[str, ...]] = {
    "economic": ("calendar",),
}

#: provider domain → the dataset keys it serves. The inverse of :data:`DATASET_DOMAIN` (+
#: :data:`EXTRA_DOMAIN_DATASETS`), and the join that lets ``sources.json`` and
#: ``freshness.json`` be rendered from one record.
DOMAIN_DATASETS: dict[str, tuple[str, ...]] = {
    domain: tuple(k for k, d in DATASET_DOMAIN.items() if d == domain)
    for domain in sorted(set(DATASET_DOMAIN.values()) | set(EXTRA_DOMAIN_DATASETS))
}
DOMAIN_DATASETS.update(EXTRA_DOMAIN_DATASETS)


def enveloped_specs() -> dict[str, DatasetSpec]:
    """Filename → spec for datasets wrapped in ``BaseEnvelope``."""
    return {name: spec for spec in DATASETS if spec.enveloped for name in spec.filenames}


def standalone_specs() -> dict[str, DatasetSpec]:
    """Filename → spec for self-describing datasets with no envelope."""
    return {name: spec for spec in DATASETS if not spec.enveloped for name in spec.filenames}


def is_known_file(name: str) -> bool:
    """Is ``name`` a file we expect to find under ``latest/``?"""
    return name in BY_FILENAME or name.endswith(NON_DATASET_SUFFIXES)


def require(key: str) -> DatasetSpec:
    """Look up a dataset by canonical key, failing loudly on an unregistered one.

    A typo'd dataset key used to fall through to a 480-minute default interval and publish a
    plausible-looking status for a dataset nobody had registered (N-1). It now raises.
    """
    try:
        return BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unregistered dataset key {key!r}; known keys: {', '.join(CANONICAL_KEYS)}"
        ) from None
