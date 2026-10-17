# ADR-0008: Heuristic mappings for derived risk indicators

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

Three configured inputs had no historical series or heuristic mapping, so each contributed a fixed 50.0 to the Global Risk Score despite changing raw values. These inputs were `cross_asset_confirmation`, `small_cap_relative`, and `semis_relative`; together they carried 21.96 points of global weight.

Git history retains the published `risk.json` input snapshot for each of the 51 risk-history dates. The latest snapshot per date reproduces that date's previously published total score, which makes an exact, targeted backfill possible without reconstructing unrelated inputs.

## Decision

- Map `cross_asset_confirmation`, a proportion from 0 to 1, linearly to the 0–100 risk-score range.
- Map `small_cap_relative` and `semis_relative` with the existing `price_vs_ma200` heuristic curve. Underperformance therefore raises risk, while relative outperformance lowers it.
- Keep dimension and indicator weights, risk-level thresholds, and the derived-history gate unchanged. Keep the overall calibration status provisional.
- Recalculate every published risk-history row and the current risk payload from the matching date's published input snapshot. Preserve the original observation timestamps.

## Consequences

- The three inputs no longer contribute a fixed 50.0 when their values are present. The weight audit reports zero unmapped weight.
- Recalculated scores can change risk levels. In the current 51-row history, two dates move from caution to low risk.
- The cross-asset dimension remains a single 15% input and exceeds the audit's 10% single-input cap. Its concentration and the relative-strength mapping curves still need multi-regime, out-of-sample review.
- Updating the fact layer changes its generation ID. Existing bilingual AI briefs still reference the previous ID and must be refreshed before they can claim alignment with the new risk result.

## Follow-up review (2026-10-12)

The post-change audit found no remaining configured indicator without a score path: 48% of configured global weight uses historical percentiles and 52% uses heuristic mappings. It still reports the 15% single-input cross-asset concentration and confirms that the historical impact is uneven across dimensions. In the current 51-row history, `liquidity_credit`, `cross_asset`, and `equity_structure` explain most of the observed score variance, while `macro`, `trend`, and `volatility` contribute much less or move against it.

No further formula, direction, threshold, or weight change is made in this follow-up. The remaining candidates—diversifying cross-asset confirmation, revisiting neutral treatment for liquidity levels, and reconciling percentile and heuristic path semantics—are calibration decisions. The available history spans only 2026-08-03 through 2026-10-12, contains two risk levels (`low_risk` and `caution`) and one regime (`goldilocks`), and uses revised rather than point-in-time source history. These observations cannot support a reliable multi-regime change.

The 1.0.1 score recalculation remains the published result: all 51 daily rows include indicator scores; the latest payload matches the last history row at 50.49 (`caution`); the 30-day and 90-day slices and fact layer match the recalculated history. No additional score changes were warranted by this follow-up. Revisit the remaining candidates when a point-in-time, multi-regime evaluation panel is available.
