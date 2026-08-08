# Market data collection matrix

Version: `1.0.0`<br>
Owner: market pipeline<br>
Cadence: each scheduled market collection

This matrix is the reviewable boundary for market history requests. A target is fetched at
most once per generation by the plan in `pipeline/collectors/market.py`; provider fallback and
last-good cache behavior remains centralized in `ProviderRegistry`.

| Consumer | Target set | Source route | Cadence / history | Value | Request boundary |
| --- | --- | --- | --- | --- | --- |
| Equity cards | `universe.us_equities` | `quotes` | Each market run / `1y` | Technical indicators and card context | One history request per symbol; bounded worker pool |
| A-share equity cards | `universe.a_share_memory` | `a_share` | Each market run / `1y` | Technical indicators where the CN history tier is available | One history request per symbol; fallback/cache is marked degraded |
| Breadth and trend | `SPY`, `IWM`, `SOXX` | `quotes` | Each market run / `1y` | Existing breadth/trend proxy inputs | One request per symbol; proxy limitations remain explicit |
| Cross-asset diagnostics | `XLY`, `XLP`, `HYG`, `IEF` | `quotes` | Each market run / `1y` | Cyclicals/defensives and high-yield/Treasury relative diagnostics | One request per symbol; diagnostic-only, no production weight |
| Sector/theme series | ETF proxies and non-CN basket constituents in `config/themes.yaml` | `quotes` | Each market run / `1y` | Theme returns and trailing percentiles | Deduplicated with equity and risk targets |

## Data expansion decision rule

No additional series is enabled only because it is available. A proposed input must identify its
consumer, source route, cadence, history requirement, analytical value, and expected request/rate
limit cost. It also needs a missing/degraded behavior and, when it affects risk scoring, a
point-in-time calibration decision. This keeps collection growth bounded and prevents an
unreviewed proxy from silently changing the production risk index.

The collector publishes request counts, unique request keys, provider outcome flags, and missing
or degraded input summaries in the canonical `market` provider status. Telemetry contains no
URLs, credentials, provider exception text, or response rows.
