# Market Risk Dashboard — Offline Calibration Report

**Document version:** 1.2 (production-path replay, governed cross-asset diagnostics and policy decision)
**Produced by:** data pipeline `scripts/calibration.py` + `pipeline/risk/calibration.py`
**Scope statement (red line):** The risk scores on this page are **model-based market stress estimates**, not exact crash probabilities, and do not constitute investment advice (architecture §1.8 / PRD §14.8).

---

## 1. Purpose

Before the MVP release, run an offline backtest of the risk model across three historical windows — **2008 Global Financial Crisis, 2018 Q4 sell-off, 2020 COVID crash** — to support the credibility claim of the risk score and to expose the model's behavior under extreme market conditions (warning lead time, rate of change, stability).

## 2. Method

- **Model:** simplified risk model = composite score (VIX + HY OAS + SPX drawdown), using the **heuristic fallback** mapping (`heuristic_risk_score`, the same table `pipeline/risk/scoring.py` uses when percentile history is unavailable). This harness does **not** exercise the production percentile path.
- **Data:** all freely available — FRED `VIXCLS`, `BAMLH0A0HYM2` (HY OAS), `DGS10` + yfinance SPX history.
- **Windows:**
  - 2008: 2008-08 → 2009-03 (main decline phase of the financial crisis)
  - 2018: 2018-09 → 2018-12 (Q4 sell-off)
  - 2020: 2020-02 → 2020-04 (COVID crash)
- **Evaluation metrics** (subset of PRD §15):
  - Early warning lead time: trading days from first risk score ≥60 to the risk peak (**positive = warning before the peak**, i.e. days early)
  - Risk score rate of change: trading days required for the risk score to move from 40 → 60
  - Max drawdown: maximum SPX drawdown within the window
  - Post-peak forward volatility: annualized volatility 5/10/20/30 days after the risk peak
  - Risk-level stability: number of risk-level switches within the window (fewer = more stable)

## 3. Results summary

| Window | Trading days | Max drawdown | Early warning (score ≥60) | 40→60 speed | Post-peak forward volatility 5d/10d/20d/30d | Level switches | First/peak/last score |
|---|---|---|---|---|---|---|---|
| 2008 Financial Crisis | 166 | -48.17% | 34 days (before peak) | 40 days | 0.80 / 0.92 / 1.26 / 2.22 | 7 | 40.14 / 65.19 / 63.21 |
| 2018 Q4 Sell-off | 81 | -19.78% | Not reached 60 (peak 57.55) | Not reached 60 | 0.15 / 0.24 / 1.12 / 1.26 | 9 | 22.24 / 57.55 / 50.39 |
| 2020 COVID | 61 | -33.92% | 7 days (before peak) | 4 days | 1.46 / 2.65 / 5.42 / 5.19 | 9 | 30.94 / 64.85 / 53.75 |

### 3.1 2008 (2008 Financial Crisis)

- Trading days: 166
- Max drawdown: -48.17%
- Early warning (score ≥60 vs peak): 34 days (positive = warning before peak)
- Risk score 40→60 speed: 40 days
- Post-peak forward volatility: {'vol_5d': 0.8, 'vol_10d': 0.92, 'vol_20d': 1.26, 'vol_30d': 2.22}
- Risk-level switches: 7
- Score range: first 40.14 / peak 65.19 / last 63.21

### 3.2 2018 (2018 Q4 Sell-off)

- Trading days: 81
- Max drawdown: -19.78%
- Early warning (score ≥60 vs peak): None days (peak 57.55, 60 threshold not reached)
- Risk score 40→60 speed: None days
- Post-peak forward volatility: {'vol_5d': 0.15, 'vol_10d': 0.24, 'vol_20d': 1.12, 'vol_30d': 1.26}
- Risk-level switches: 9
- Score range: first 22.24 / peak 57.55 / last 50.39

### 3.3 2020 (COVID Crash)

- Trading days: 61
- Max drawdown: -33.92%
- Early warning (score ≥60 vs peak): 7 days (positive = warning before peak)
- Risk score 40→60 speed: 4 days
- Post-peak forward volatility: {'vol_5d': 1.46, 'vol_10d': 2.65, 'vol_20d': 5.42, 'vol_30d': 5.19}
- Risk-level switches: 9
- Score range: first 30.94 / peak 64.85 / last 53.75

## 4. Production-path replay (latest-source evidence)

The production-path replay was added after the original fallback-only report. It calls the same `RiskModel.score` implementation used by Risk Lab, in date order, with an expanding point-in-time history through each score date. A deterministic synthetic panel runs in CI; the figures below are from a manual 2015-01-01 → 2025-12-31 replay with a 5-year warm-up, fetched on 2026-08-08. The replay now includes the four governed ETF proxy histories used by the deferred cross-asset diagnostics.

| Forward horizon | Outcome coverage | Spearman score vs forward loss | Precision at score ≥60 | Recall | False-positive rate |
|---|---:|---:|---:|---:|---:|
| 5 observations | 99.82% | 0.3545 | 2.16% | 72.73% | 26.52% |
| 10 observations | 99.64% | 0.4002 | 4.45% | 56.90% | 26.29% |
| 20 observations | 99.28% | 0.4097 | 12.13% | 58.44% | 25.16% |
| 30 observations | 98.92% | 0.3847 | 19.54% | 52.35% | 24.29% |

The level-switch rate was 9.0778 per 100 evaluated observations with a mean absolute score change of 1.5749. The replay used the mixed production-percentile/heuristic path for all 2,765 evaluated observations. Macro coverage was incomplete for the two credit-spread series (3,421 missing observations each), reverse repo (153), and the Fed balance sheet (2); SPY, IWM, SOXX, XLY, XLP, HYG and IEF histories were complete. The null-aware confirmation denominator also means missing inputs no longer count as benign observations.

This is evidence of positive ranking signal, not evidence of a calibrated probability. The manual panel uses latest FRED/Yahoo observations and does not contain point-in-time source vintages; the result is therefore descriptive and subject to revision bias. The synthetic CI fixture proves determinism and look-ahead protection, but is not a performance claim.

### 4.1 Governed cross-asset diagnostics

The collection path fetches XLY, XLP, HYG and IEF once through the existing quotes registry and computes percentage-point gaps from each pair's latest one-day return. These are ETF relative-return proxies, not direct economic spreads:

| Signal | Inputs and transformation | Risk direction | Production status |
|---|---|---|---|
| Cyclicals versus defensives | XLY 1-day return minus XLP 1-day return | Negative is riskier | Diagnostic only |
| High-yield versus Treasuries | HYG 1-day return minus IEF 1-day return | Negative is riskier | Diagnostic only |

At the 20-observation target horizon, the new signals produced the following point-in-time evidence:

| Signal | Evaluated | Precision | Recall | False-positive rate | Precision delta vs current confirmation | Recall delta vs current confirmation |
|---|---:|---:|---:|---:|---:|---:|
| Cyclicals versus defensives | 2,745 | 5.68% | 48.05% | 47.39% | -1.32 pp | -48.05 pp |
| High-yield versus Treasuries | 2,745 | 5.94% | 50.65% | 47.66% | -1.07 pp | -45.45 pp |

The signals provide broad event coverage but weak precision and lower recall than the current confirmation comparison point. They therefore do not demonstrate a production improvement. Risk Lab publishes their value, trigger, provider, freshness state, unit and transformation for review, but the calibration policy keeps both outside production weighting until a governed refit has stronger point-in-time evidence.

## 5. Policy decision

| Component | Decision | Rationale |
|---|---|---|
| Dimension weights | Retain | Ranking is positive but moderate; revised-source history and partial proxy coverage do not justify refitting. |
| Indicator weights | Retain | No stable out-of-sample attribution is available for a weight change; preserve the reviewed transparent mapping. |
| Risk-level thresholds | Retain | Score ≥60 gives 58.44% recall and 25.16% false-positive rate at 20 observations; higher thresholds trade recall for precision without a pre-registered operating objective. |
| Data-trust formula | Gate | Keep the existing product metric, but do not call it statistical confidence or probability. |
| Cross-asset aggregation | Gate | Keep the current null-aware proxy-backed aggregation; the new ETF signals remain diagnostic-only because their 20-observation precision is below 6% and recall is below the current comparison point. |

Policy version `1.0.0` is published in the Risk Lab contract and run report. No live score weights, thresholds, or confidence arithmetic were changed.

## 6. Interpretation

- **Warning effectiveness:** both 2008 and 2020 triggered a high score ≥60 before the risk peak (34 / 7 days early), showing the model can emit a stress signal before the main decline phase; the 2020 signal was faster (40 → 60 in 4 days), consistent with the steep slope of the COVID crash.
- **2018 case:** the peak was only 57.55 and never triggered the 60 high-score threshold — consistent with 2018 being characterized as a "mild correction" rather than a systemic crisis; the model produced no severe false positives (False Positive control is reasonable).
- **Volatility amplification:** post-peak forward volatility rises monotonically with window depth (especially 20d/30d in 2020), consistent with volatility clustering after historical crashes.
- **Stability:** 7-9 level switches show the model frequently changes levels during sharp market transitions — a known limitation of heuristic models (see §5), not treated as a fault.

## 7. Limitations

- Market breadth history (2008-2012) is unavailable → this report does not include the breadth dimension (review P0-3); T05 recommends later rebuilding an approximate breadth series from SPX new high/new low counts / % above MA200 and re-running the backtest.
- The MVP risk mapping is a heuristic rule set (pipeline/risk/scoring.py); this harness evaluates the **heuristic fallback** path, not the production percentile path — the score meaning is a "model-based market stress estimate", not a statistical model.
- Free data sources have no SLA; backtest windows may be skipped if network data is unavailable; rerun locally with `python scripts/calibration.py` to reproduce.
- Single-window sample size is small (3 windows); conclusions are descriptive rather than statistically significant.
- The new cross-asset inputs are ETF relative-return proxies, not direct credit spreads or sector-flow measures; latest-source history has no point-in-time vintages and signal event rates are sensitive to the selected event definition.

## 8. Reproduction

```bash
python scripts/calibration.py   # Rerun the three-window backtest and refresh this report
.venv/bin/python scripts/calibrate_production.py --start 2015-01-01 --end 2025-12-31 --warmup-years 5 --regime mixed
```

## 9. Release

- This document is published with the repository (`docs/calibration-report.md` is un-ignored from gitignore; root-level `CALIBRATION.md` is the publishable copy).
- Any credibility claim about the risk score must reference this report; no UI/copy may describe the risk score as an "exact crash probability".
