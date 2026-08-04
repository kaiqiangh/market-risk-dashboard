# Config is a fact, not documentation

`config/risk_model.yaml` lists indicators the risk model has never computed. Eight keys — `inflation_surprise`, `labor_deterioration`, `move_index`, `vix_term_structure`, `vol_risk_premium`, `equal_weight_divergence`, `treasury_general_account`, `bank_reserves` — sit in the `indicators` block with a source and a metric, and `pipeline/risk/model.py` never reads any of them.

The `liquidity` FRED group is a partial case, not a total one. `WALCL` and `RRPONTSYD` **are** fetched and **are** registered, as `fed_balance_sheet` (weight 5.0) and `reverse_repo` (weight 5.0) in `_liquidity_indicators`. Only `WTREGEN` and `WRESBAL` are absent from `DEFAULT_SERIES` — and those are exactly the two phantom config keys `treasury_general_account` and `bank_reserves`. So there is one defect here, not two: two config keys with no data and no reader.

Both directions of drift are the same failure: a reader — human or agent — treats the YAML as a description of what the system does, and the YAML is fiction. The weights look tuned. The thresholds look considered. Nothing reads them. This is worse than an undocumented system, because it manufactures false confidence about coverage.

We rejected "implement the missing indicators to match the config" — that is eight new data dependencies chosen by whoever last edited a YAML file, not by anyone reasoning about the model. We rejected "add a comment saying these are aspirational" — comments do not fail builds. We chose **config trails implementation, and drift is a test failure**: trim the YAML to exactly what the model computes, then add a test that walks the config keys and the model's registered indicator keys and asserts they are the same set.

An earlier draft of this ADR carved out the `liquidity` group as an exception to be *implemented* rather than trimmed, on the grounds that its absence starved the `liquidity_credit` dimension. That justification does not survive contact with the code: the dimension already carries `fed_balance_sheet`, `reverse_repo` and `hy_oas`, so it is not starved. With the premise gone, the exception goes with it. **All eight phantom keys are trimmed, including `treasury_general_account` and `bank_reserves`.** Adding TGA and bank reserves is a defensible future change, but it should be argued on its own merits in its own ticket — not smuggled in because someone once typed it into a YAML file.

Config-trails-implementation is therefore the rule without exception here. Promoting a config entry to implemented is a deliberate act with a ticket behind it, never a side effect of editing YAML.

Two related consistency bugs fall out of the same principle, because they are also cases of two artifacts disagreeing about one fact:

- `yield_curve_10y2y` is declared `higher_is_riskier` in `model.py` while `HEURISTIC_RULES` in `scoring.py` scores an *inverted* curve (low value) as high risk. Both cannot be true. The heuristic is right — curve inversion is the recession signal — so the direction declaration is the bug, and a test asserts the two agree in sign.
- `hy_oas` is registered in both `_macro_indicators` (weight 5.0) and `_liquidity_indicators` (weight 10.0), so credit spreads are counted twice under two dimension budgets. One indicator, one home — and the config already declares which home: `hy_oas` appears only under `liquidity_credit`. The weight-5.0 registration in `_macro_indicators` is the one that goes. The drift test grows a third assertion to make the class of bug unrepeatable: no indicator key may be registered in more than one dimension.

## Consequences

- A new `tests/pipeline/test_config_drift.py` owns the config↔implementation contract. It is the only place that has to change when an indicator is genuinely added.
- Adding an indicator becomes a two-file change (config + model) that the test forces you to complete. Editing YAML alone now fails CI, which is the intended friction.
- Dimension weights in `config/risk_model.yaml` stay authoritative — this ADR narrows what may appear in the `indicators` block, not who owns weighting.
- `percentile_5y` is renamed to reflect what `percentile_in_window` actually computes (the latest value's rank within the available window, typically ~1y of daily bars, not a 5-year percentile). Same class of defect: the name asserted a fact the code did not deliver.
- The calibration harness backtests the heuristic fallback path, not the percentile path that runs in production, and its sign convention is reversed. It keeps running, with the label corrected to say which path it measures — a calibration number that misstates its own scope is config drift wearing a lab coat.
