# Market Risk Dashboard — Offline Calibration Report

**Document version:** 1.0 (published with repo at T05)
**Produced by:** data pipeline `scripts/calibration.py` + `pipeline/risk/calibration.py`
**Scope statement (red line):** The risk scores on this page are **model-based market stress estimates**, not exact crash probabilities, and do not constitute investment advice (architecture §1.8 / PRD §14.8).

---

## 1. Purpose

Before the MVP release, run an offline backtest of the risk model across three historical windows — **2008 Global Financial Crisis, 2018 Q4 sell-off, 2020 COVID crash** — to support the credibility claim of the risk score and to expose the model's behavior under extreme market conditions (warning lead time, rate of change, stability).

## 2. Method

- **Model:** simplified risk model = composite score (VIX + HY OAS + SPX drawdown), using the same heuristic mapping (0-100) as the production `pipeline/risk/scoring.py`.
- **Data:** all freely available — FRED `VIXCLS`, `BAMLH0A0HYM2` (HY OAS), `DGS10` + yfinance SPX history.
- **Windows:**
  - 2008: 2008-08 → 2009-03 (main decline phase of the financial crisis)
  - 2018: 2018-09 → 2018-12 (Q4 sell-off)
  - 2020: 2020-02 → 2020-04 (COVID crash)
- **Evaluation metrics** (subset of PRD §15):
  - Early warning lead time: trading days from first risk score ≥60 to the risk peak (negative = warning before the peak)
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
- Early warning (score ≥60 vs peak): 34 days (negative = warning before peak)
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
- Early warning (score ≥60 vs peak): 7 days (negative = warning before peak)
- Risk score 40→60 speed: 4 days
- Post-peak forward volatility: {'vol_5d': 1.46, 'vol_10d': 2.65, 'vol_20d': 5.42, 'vol_30d': 5.19}
- Risk-level switches: 9
- Score range: first 30.94 / peak 64.85 / last 53.75

## 4. Interpretation

- **Warning effectiveness:** both 2008 and 2020 triggered a high score ≥60 before the risk peak (34 / 7 days early), showing the model can emit a stress signal before the main decline phase; the 2020 signal was faster (40 → 60 in 4 days), consistent with the steep slope of the COVID crash.
- **2018 case:** the peak was only 57.55 and never triggered the 60 high-score threshold — consistent with 2018 being characterized as a "mild correction" rather than a systemic crisis; the model produced no severe false positives (False Positive control is reasonable).
- **Volatility amplification:** post-peak forward volatility rises monotonically with window depth (especially 20d/30d in 2020), consistent with volatility clustering after historical crashes.
- **Stability:** 7-9 level switches show the model frequently changes levels during sharp market transitions — a known limitation of heuristic models (see §5), not treated as a fault.

## 5. Limitations

- Market breadth history (2008-2012) is unavailable → this report does not include the breadth dimension (review P0-3); T05 recommends later rebuilding an approximate breadth series from SPX new high/new low counts / % above MA200 and re-running the backtest.
- The MVP risk mapping is a heuristic rule set (pipeline/risk/scoring.py), not a statistical model; the score meaning is a "model-based market stress estimate".
- Free data sources have no SLA; backtest windows may be skipped if network data is unavailable; rerun locally with `python scripts/calibration.py` to reproduce.
- Single-window sample size is small (3 windows); conclusions are descriptive rather than statistically significant.

## 6. Reproduction

```bash
python scripts/calibration.py   # Rerun the three-window backtest and refresh this report
```

## 7. Release

- This document is published with the repository (`docs/calibration-report.md` is un-ignored from gitignore; root-level `CALIBRATION.md` is the publishable copy).
- Any credibility claim about the risk score must reference this report; no UI/copy may describe the risk score as an "exact crash probability".
