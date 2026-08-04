# Three-family color semantics (risk / direction / freshness)

The legacy palette overloaded five tones (`low/caution/high/severe/na`) across five different meanings: risk level, market regime, price direction, risk trend, and data freshness — so the same green meant "low risk", "price up", "risk improving", and "data fresh" simultaneously. For the dark-first terminal redesign we split color into three dedicated token families:

- **`risk-*`** (low / caution / high / severe / na) — a muted ramp used *exclusively* for risk level and market regime. This is the only place saturated color appears by default, so risk and anomaly signals are immediately visible.
- **`dir-*`** (up / down) — price/asset direction, deliberately de-emphasized (~60–70% of risk-ramp saturation) and always paired with an explicit `+`/`-` sign and tabular numerals. One global Western convention: green up / red down. The token split makes a future per-locale or per-user flip a two-line change; locale-switching colors was rejected as a maintenance trap.
- **`fresh-*`** — data freshness communicates through icon + text + muted styling; only `stale`/`missing` earn a warm tone. "Fresh" is the expected state and consumes no color budget.

This was a real trade-off: the alternative (keep one tone ramp for everything) is less code but makes anomaly signals invisible in a sea of green — the exact "trading terminal full of green numbers" failure the redesign bans. It is hard to reverse because every component's color usage is rewritten against the new families.

## Consequences

- `riskColors.ts` gains separate tone mappers per family instead of routing all semantics through `RiskTone`.
- The 6-level risk enum keeps its existing 6→4 tone collapse (`risk_on`≡`low_risk`, `severe_risk`≡`crisis`) — a product decision, unchanged.
- Architecture §8.6 still applies: color is never the only signal — always text + icon + value.
- **AA tuning deviation (2026-08-03, spec #23 ticket #34):** the values approved in the design mockup were retuned at the token level to pass the WCAG AA 4.5:1 gate — dark `risk-severe` #cc5252→#d96565, `risk-na` #5f6b7f→#7d8aa0; light `primary` #3d7ca8→#38729c, `risk-caution`/`fresh-warn` #9a7433→#8f6b2d, `dir-up` #4d8568→#467c60. The token *semantics* are unchanged; only the tuned values differ from the mockup. Enforced by the contrast test suite in `tests/frontend/tokens.test.ts`.
