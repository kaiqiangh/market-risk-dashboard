"""#67: the configured indicator set and the scored indicator set are the same set.

Config (config/risk_model.yaml `indicators:`) is a fact, not documentation (ADR 0005).
These tests assert the two sets are identical in both directions and that no indicator
is registered in two dimensions (ruling B) — the `hy_oas` double-count must be
unrepeatable, not merely fixed.
"""

from __future__ import annotations

from pipeline.risk.model import RiskModel
from pipeline.schemas.envelope import SCHEMA_VERSION
from pipeline.settings import Settings
from tests.pipeline.factories import make_envelope

#: Dimension name -> builder method name on RiskModel.
_DIMENSION_BUILDERS: dict[str, str] = {
    "macro": "_macro_indicators",
    "liquidity_credit": "_liquidity_indicators",
    "equity_structure": "_equity_structure_indicators",
    "volatility": "_volatility_indicators",
    "cross_asset": "_cross_asset_indicators",
    "trend": "_trend_indicators",
}


def _config_indicator_keys() -> dict[str, set[str]]:
    """The indicator key set declared in config/risk_model.yaml, per dimension."""
    raw = Settings(_env_file=None).load_risk_model()
    indicators = raw.get("indicators", {})
    return {dim: {str(item["key"]) for item in entries} for dim, entries in indicators.items()}


def _code_indicator_keys() -> dict[str, set[str]]:
    """The indicator key set actually registered by pipeline/risk/model.py, per dimension.

    The builders always return their full indicator list (values may be None), so calling
    them with an empty context registers every indicator without needing data.
    """
    model = RiskModel()
    return {dim: {i.key for i in getattr(model, builder)({})} for dim, builder in _DIMENSION_BUILDERS.items()}


def _drift() -> tuple[dict[str, set[str]], dict[str, set[str]], list[str]]:
    """Return (config_keys, code_keys, list of double-registered keys)."""
    config_keys = _config_indicator_keys()
    code_keys = _code_indicator_keys()
    seen: dict[str, str] = {}
    double: list[str] = []
    for dim, keys in code_keys.items():
        for key in keys:
            if key in seen:
                double.append(f"{key} in {seen[key]} and {dim}")
            seen[key] = dim
    return config_keys, code_keys, double


def test_every_config_key_is_registered() -> None:
    """Config ⊆ code: a declared indicator that is never scored is a phantom (#67 group 1)."""
    config_keys, code_keys, _ = _drift()
    missing: list[str] = []
    for dim, keys in config_keys.items():
        for key in keys:
            if key not in code_keys.get(dim, set()):
                missing.append(f"{dim}/{key}")
    assert not missing, f"declared in config but never registered in model.py: {missing}"


def test_every_registered_key_is_in_config() -> None:
    """Code ⊆ config: a scored indicator that is never declared drifts from configuration."""
    config_keys, code_keys, _ = _drift()
    undeclared: list[str] = []
    for dim, keys in code_keys.items():
        for key in keys:
            if key not in config_keys.get(dim, set()):
                undeclared.append(f"{dim}/{key}")
    assert not undeclared, f"registered in model.py but not declared in config: {undeclared}"


def test_no_indicator_registered_in_two_dimensions() -> None:
    """Ruling B: one indicator in one dimension. hy_oas scored once, at weight 10.0."""
    config_keys, code_keys, double = _drift()
    assert not double, f"indicator registered in two dimensions: {double}"

    # The named regression this rule exists for: hy_oas appears exactly once, under
    # liquidity_credit, at weight 10.0 (the macro registration is gone).
    model = RiskModel()
    hy_oas_sites = [
        (dim, ind.weight)
        for dim in _DIMENSION_BUILDERS
        for ind in getattr(model, _DIMENSION_BUILDERS[dim])({})
        if ind.key == "hy_oas"
    ]
    assert hy_oas_sites == [("liquidity_credit", 10.0)], f"hy_oas must be scored once at 10.0, found {hy_oas_sites}"


def test_macro_registers_exactly_the_four_real_macro_indicators() -> None:
    """#67 group 4: `_macro_indicators` is rates + curve + dollar + nominal yield."""
    model = RiskModel()
    keys = {i.key for i in model._macro_indicators({})}
    assert keys == {"real_rate_dfii10", "yield_curve_10y2y", "dollar_index", "dgs10"}


def test_no_dxy_indicator_key_survives() -> None:
    """The code-side indicator key is `dollar_index`; `dxy` must not be registered."""
    code_keys, _ = _config_indicator_keys(), None
    _, code_keys, _ = _drift()
    for dim, keys in code_keys.items():
        assert "dxy" not in keys, f"dxy must be renamed to dollar_index, found under {dim}"


def test_published_artifacts_carry_schema_version_1_1_0() -> None:
    """The release-wide bump is landed: generated documents carry SCHEMA_VERSION = 1.1.0."""
    assert SCHEMA_VERSION == "1.1.0"
    doc = make_envelope("risk")
    assert doc["schema_version"] == "1.1.0"
