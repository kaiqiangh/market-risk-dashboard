/**
 * Hand-written inline documents for frontend tests (#73).
 *
 * Since #73 the only committed fixture files are the three goldens
 * (tests/fixtures/{risk.json, analysis.zh-CN.json, facts.json}). Every other document the
 * frontend suite needs is defined here: frozen hand-written documents, independent of the
 * Python factory, shared by the fetch mock and the Zod contract tests.
 */

export const macroFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "fred",
  provenance: { provider: "fred", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:30:00Z",
  freshness_status: "fresh",
  data_quality: 0.95,
  payload: {
    rates: [
      {
        key: "dgs10",
        label: "10-Year Treasury Yield",
        value: 4.21,
        previous: 4.18,
        change_1m: 0.15,
        unit: "pct",
        source: "FRED",
        updated_at: "2026-08-03T09:30:00Z",
        status: "fresh",
      },
    ],
    credit: [
      {
        key: "bamlh0a0hym2",
        label: "ICE BofA US High Yield OAS",
        value: 3.42,
        previous: 3.5,
        change_1m: -0.08,
        unit: "pct",
        source: "FRED",
        updated_at: "2026-08-03T09:30:00Z",
        status: "fresh",
      },
    ],
    // #96: VIX lives in its own volatility group, not under rates.
    volatility: [
      {
        key: "vixcls",
        label: "CBOE Volatility Index (VIX)",
        value: 16.8,
        previous: 17.2,
        change_1m: -2.4,
        unit: "index",
        source: "FRED",
        updated_at: "2026-08-03T09:30:00Z",
        status: "fresh",
      },
    ],
    inflation: [
      {
        key: "cpiaucsl",
        label: "CPI All Urban Consumers (YoY)",
        value: 3.46,
        previous: 3.5,
        change_1m: -0.04,
        unit: "pct",
        source: "FRED",
        updated_at: "2026-07-01T00:00:00Z",
        status: "fresh",
      },
    ],
    labor: [
      {
        key: "unrate",
        label: "Unemployment Rate",
        value: 4.2,
        previous: 4.3,
        change_1m: -0.1,
        unit: "pct",
        source: "FRED",
        updated_at: "2026-07-01T00:00:00Z",
        status: "fresh",
      },
    ],
    liquidity: [
      {
        key: "walcl",
        label: "Fed Total Assets",
        value: 6600000,
        previous: 6580000,
        change_1m: 20000,
        unit: "usd",
        source: "FRED",
        updated_at: "2026-07-30T00:00:00Z",
        status: "fresh",
      },
    ],
    fx: [
      {
        key: "dtwexbgs",
        label: "Nominal Broad Dollar Index",
        value: 118.6,
        previous: 118.1,
        change_1m: 0.5,
        unit: "index",
        source: "FRED",
        updated_at: "2026-08-01T00:00:00Z",
        status: "fresh",
      },
    ],
    fedwatch: null,
  },
};

/** history/macro/fx.30d.json — sparse column-oriented bundle (#96/#84 §3). */
export const macroHistoryFxFixture = {
  DTWEXBGS: {
    d: ["2026-07-03", "2026-07-06", "2026-07-07"],
    v: [118.1, 118.3, 118.6],
  },
  DEXUSEU: {
    d: ["2026-07-03", "2026-07-06", "2026-07-07"],
    v: [1.0842, 1.0831, 1.0824],
  },
};

export const equitiesFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "yfinance",
  provenance: { provider: "yfinance", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:45:00Z",
  freshness_status: "fresh",
  data_quality: 0.9,
  payload: {
    assets: [
      {
        symbol: "NVDA",
        name: "NVIDIA",
        name_zh: "英伟达",
        market: "US",
        sector: "semis",
        theme: ["AI", "GPU"],
        price: 128.4,
        currency: "USD",
        change_1d: -2.1,
        change_1w: 3.5,
        change_1m: 8.2,
        change_ytd: 42.0,
        volume: 250000000,
        market_cap: 3200000000000,
        ma50_distance_pct: 4.1,
        ma200_distance_pct: 18.3,
        rsi14: 61.0,
        percentile_1y: 88.0,
        percentile_1y_obs: 250,
        source: "yfinance",
        updated_at: "2026-08-03T10:00:00Z",
        is_proxy: false,
      },
      {
        symbol: "603986.SH",
        name: "GigaDevice",
        name_zh: "兆易创新",
        market: "CN",
        sector: "semis",
        theme: ["Memory", "NOR"],
        price: 96.5,
        currency: "CNY",
        change_1d: 1.2,
        change_1w: -0.8,
        change_1m: 5.6,
        change_ytd: 12.3,
        volume: 15000000,
        market_cap: 64000000000,
        ma50_distance_pct: 2.2,
        ma200_distance_pct: 9.8,
        rsi14: 55.0,
        percentile_1y: 70.0,
        percentile_1y_obs: 250,
        source: "akshare",
        updated_at: "2026-08-03T10:00:00Z",
        is_proxy: false,
      },
    ],
  },
};

export const sectorsFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "yfinance",
  provenance: { provider: "yfinance", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:45:00Z",
  freshness_status: "fresh",
  data_quality: 0.85,
  payload: {
    // No label/label_zh on sectors/themes rows since #102 (C-1): the payload carries the
    // key and the numbers; the frontend renders t(themes.<key>).
    sectors: [
      {
        key: "semis",
        change_1d: -1.8,
        change_1w: 2.1,
        change_1m: 7.4,
        percentile_1y: 82.0,
        percentile_1y_obs: 250,
        updated_at: "2026-08-03T10:00:00Z",
      },
    ],
    themes: [
      {
        key: "memory",
        change_1d: -2.4,
        change_1w: 1.9,
        change_1m: 12.6,
        percentile_1y: 90.0,
        percentile_1y_obs: 250,
        constituents: ["MU", "SNDK", "WDC", "STX"],
        updated_at: "2026-08-03T10:00:00Z",
      },
      {
        key: "cybersecurity",
        change_1d: 0.8,
        change_1w: 2.2,
        change_1m: 4.1,
        percentile_1y: null,
        percentile_1y_obs: 30,
        constituents: ["PANW", "CRWD", "FTNT", "ZS"],
        updated_at: "2026-08-03T10:00:00Z",
      },
    ],
    memory: {
      label: "Memory proxy (MU / 000660.KS / 005930.KS)",
      label_zh: "存储周期代理（美光/海力士/三星）",
      change_1w: 2.3,
      change_1m: 11.8,
      note: "Proxy using memory-maker equities; DRAM/NAND spot prices are paywalled (V2).",
      updated_at: "2026-08-03T10:00:00Z",
    },
  },
};

export const cryptoFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "coingecko",
  provenance: { provider: "coingecko", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:50:00Z",
  freshness_status: "fresh",
  data_quality: 0.88,
  payload: {
    assets: [
      {
        symbol: "BTC",
        name: "Bitcoin",
        price: 64000.0,
        change_1d: -0.8,
        change_1w: 2.4,
        change_1m: 6.1,
        market_cap: 1260000000000,
        volume_24h: 28000000000,
        source: "coingecko",
        updated_at: "2026-08-03T10:00:00Z",
      },
    ],
    btc_dominance: 0.54,
    stablecoin_mcap: 168000000000,
    market_cap_total: 2330000000000,
    sentiment: "neutral",
  },
};

export const commoditiesFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "yfinance",
  provenance: { provider: "yfinance", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:45:00Z",
  freshness_status: "fresh",
  data_quality: 0.9,
  payload: {
    assets: [
      {
        symbol: "GC=F",
        name: "Gold",
        name_zh: "黄金",
        price: 2450.5,
        currency: "USD",
        change_1d: 0.8,
        change_1w: 1.2,
        change_1m: 3.4,
        source: "yfinance",
        updated_at: "2026-08-03T10:00:00Z",
      },
      {
        symbol: "CL=F",
        name: "WTI Crude",
        name_zh: "WTI 原油",
        price: 78.4,
        currency: "USD",
        change_1d: -1.5,
        change_1w: -2.1,
        change_1m: -4.2,
        source: "yfinance",
        updated_at: "2026-08-03T10:00:00Z",
      },
    ],
  },
};

export const newsFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "rss_news",
  provenance: { provider: "rss_news", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:55:00Z",
  freshness_status: "fresh",
  data_quality: 0.8,
  payload: {
    items: [
      {
        id: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
        title: "Fed signals patience on rate cuts as inflation lingers",
        title_zh: null,
        source: "CNBC",
        url: "https://www.cnbc.com/2026/08/03/fed-patience.html",
        published_at: "2026-08-03T09:00:00Z",
        categories: ["monetary_policy"],
        assets: ["NVDA", "BTC"],
        importance: 85.0,
        sentiment: "neutral",
        summary:
          "Federal Reserve officials signal patience on rate cuts while inflation remains above target.",
        impact_window: "1w",
      },
    ],
    total: 1,
    updated_at: "2026-08-03T10:00:00Z",
  },
};

export const calendarFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "fmp",
  provenance: { provider: "fmp", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T08:00:00Z",
  freshness_status: "fresh",
  data_quality: 0.9,
  payload: {
    events: [
      {
        id: "econ-CPI-2026-08-13",
        type: "economic",
        title: "CPI YoY",
        country: "US",
        datetime: "2026-08-13T12:30:00Z",
        importance: "high",
        actual: null,
        forecast: 3.1,
        previous: 3.2,
        unit: "pct",
        related_assets: ["NVDA", "BTC"],
        source: "fred",
      },
      {
        id: "earnings-NVDA-2026-08-27",
        type: "earnings",
        title: "NVIDIA Q2 FY27 Earnings",
        country: "US",
        datetime: "2026-08-27T20:00:00Z",
        importance: "high",
        actual: null,
        forecast: null,
        previous: null,
        unit: null,
        related_assets: ["NVDA"],
        source: "fmp",
      },
    ],
    updated_at: "2026-08-03T10:00:00Z",
  },
};

export const dashboardFixture = {
  generated_at: "2026-08-03T10:00:00Z",
  schema_version: "1.0.0",
  source: "risk_model",
  provenance: { provider: "risk_model", used_fallback: false, from_cache: false },
  source_updated_at: "2026-08-03T09:45:00Z",
  freshness_status: "fresh",
  data_quality: 0.9,
  payload: {
    risk: {
      model_version: "1.0.0",
      generated_at: "2026-08-03T10:00:00Z",
      total_score: 52.3,
      risk_level: "caution",
      trend_1d: 1.4,
      trend_1w: 3.2,
      trend_1m: -2.1,
      dimensions: [
        {
          key: "macro",
          label: "Macro",
          weight: 20.0,
          effective_weight: 20.0,
          score: 45.0,
          indicators: [
            {
              key: "real_rate_dfii10",
              label: "10Y Real Rate",
              value: 1.9,
              percentile: 72.0,
              z_score: 0.8,
              risk_score: 62.0,
              direction: "higher_is_riskier",
              weight: 5.0,
              source: "FRED",
              updated_at: "2026-08-03T09:30:00Z",
              status: "fresh",
              is_proxy: false,
            },
          ],
          coverage: 0.83,
          trend: "rising",
        },
        {
          key: "liquidity_credit",
          label: "Liquidity & Credit",
          weight: 20.0,
          effective_weight: 20.0,
          score: 40.0,
          indicators: [
            {
              key: "hy_oas",
              label: "HY OAS",
              value: 3.4,
              percentile: 45.0,
              z_score: 0.1,
              risk_score: 40.0,
              direction: "higher_is_riskier",
              weight: 5.0,
              source: "FRED",
              updated_at: "2026-08-03T09:30:00Z",
              status: "fresh",
              is_proxy: false,
            },
          ],
          coverage: 0.75,
          trend: "flat",
        },
        {
          key: "equity_structure",
          label: "Equity Structure",
          weight: 20.0,
          effective_weight: 20.0,
          score: 55.0,
          indicators: [
            {
              key: "breadth_above_ma200",
              label: "Breadth above MA200",
              value: 0.62,
              percentile: 58.0,
              z_score: 0.3,
              risk_score: 55.0,
              direction: "lower_is_riskier",
              weight: 5.0,
              source: "computed",
              updated_at: "2026-08-03T10:00:00Z",
              status: "fresh",
              is_proxy: false,
            },
          ],
          coverage: 0.6,
          trend: "falling",
        },
        {
          key: "volatility",
          label: "Volatility",
          weight: 15.0,
          effective_weight: 15.0,
          score: 35.0,
          indicators: [
            {
              key: "vix",
              label: "VIX",
              value: 18.4,
              percentile: 40.0,
              z_score: -0.2,
              risk_score: 35.0,
              direction: "higher_is_riskier",
              weight: 4.0,
              source: "FRED",
              updated_at: "2026-08-03T09:30:00Z",
              status: "fresh",
              is_proxy: false,
            },
          ],
          coverage: 0.8,
          trend: "rising",
        },
        {
          key: "cross_asset",
          label: "Cross Asset",
          weight: 15.0,
          effective_weight: 15.0,
          score: 60.0,
          indicators: [
            {
              key: "cross_asset_confirmation",
              label: "Cross-asset confirmation",
              value: 0.55,
              percentile: 65.0,
              z_score: 0.6,
              risk_score: 60.0,
              direction: "higher_is_riskier",
              weight: 4.0,
              source: "computed",
              updated_at: "2026-08-03T10:00:00Z",
              status: "fresh",
              is_proxy: true,
            },
          ],
          coverage: 0.7,
          trend: "rising",
        },
        {
          key: "trend",
          label: "Trend",
          weight: 10.0,
          effective_weight: 10.0,
          score: 48.0,
          indicators: [
            {
              key: "price_vs_ma200",
              label: "Price vs MA200",
              value: 12.5,
              percentile: 78.0,
              z_score: 1.1,
              risk_score: 48.0,
              direction: "lower_is_riskier",
              weight: 3.0,
              source: "computed",
              updated_at: "2026-08-03T10:00:00Z",
              status: "fresh",
              is_proxy: false,
            },
          ],
          coverage: 0.9,
          trend: "flat",
        },
      ],
      top_drivers: [
        {
          dimension_key: "macro",
          indicator_key: "real_rate_dfii10",
          label: "10Y Real Rate",
          contribution: 12.4,
          change_1d: 0.5,
          evidence_ref: {
            dataset: "macro",
            path: "payload.rates[0].value",
            metric: "real_rate_dfii10",
            value: 1.9,
            updated_at: "2026-08-03T09:30:00Z",
          },
          is_proxy: false,
          discount: 1.0,
        },
        {
          dimension_key: "cross_asset",
          indicator_key: "cross_asset_confirmation",
          label: "Cross-asset confirmation",
          contribution: 9.0,
          change_1d: 0.3,
          evidence_ref: null,
          is_proxy: true,
          discount: 0.8,
        },
      ],
      breadth: {
        breadth_above_ma200: 0.6,
        breadth_qualifying: 11,
        breadth_considered: 18,
        new_highs_ratio: 0.4,
        new_lows_ratio: 0.2,
        new_highs_qualifying: 7,
        new_lows_qualifying: 4,
        new_considered: 18,
        small_cap_relative: -1.0,
        semis_relative: 2.0,
        is_proxy: true,
        note: "MVP breadth uses index proxies (SPY/IWM/SOXX)",
      },
      regime: "late_cycle",
      regime_evidence: ["10Y-2Y spread near inversion", "HY OAS widening"],
      confidence: 0.72,
      confidence_factors: { data_quality: 0.9, coverage: 0.83, consistency: 0.6 },
      disclaimer:
        "The risk score on this page is a model-based estimate of market stress, not a precise probability of a market crash, and should not be considered investment advice.",
    },
    regime: "late_cycle",
    top_drivers: [
      {
        dimension_key: "macro",
        indicator_key: "real_rate_dfii10",
        label: "10Y Real Rate",
        contribution: 12.4,
        change_1d: 0.5,
        evidence_ref: {
          dataset: "macro",
          path: "payload.rates[0].value",
          metric: "real_rate_dfii10",
          value: 1.9,
          updated_at: "2026-08-03T09:30:00Z",
        },
        is_proxy: false,
        discount: 1.0,
      },
      {
        dimension_key: "cross_asset",
        indicator_key: "cross_asset_confirmation",
        label: "Cross-asset confirmation",
        contribution: 9.0,
        change_1d: 0.3,
        evidence_ref: null,
        is_proxy: true,
        discount: 0.8,
      },
    ],
    cross_asset: [
      { asset: "NVDA", category: "equity", change_1d: 1.2 },
      { asset: "BTC", category: "crypto", change_1d: -0.5 },
    ],
    catalysts: [
      {
        type: "earnings",
        title: "NVDA Earnings",
        datetime: "2026-08-19T12:00:00Z",
        importance: "high",
        related_assets: ["NVDA"],
      },
    ],
    sector_performance: [
      { key: "semis", label: "Semiconductors", label_zh: "半导体", change_1d: 0.8 },
      { key: "memory", label: "Memory", label_zh: "存储", change_1d: -1.1 },
    ],
  },
};

export const analysisEnFixture = {
  schema_version: "1.0.0",
  generated_at: "2026-08-03T10:30:00Z",
  language: "en",
  market_state: "caution",
  market_regime: "late_cycle",
  summary:
    "The market is in a caution regime with a total risk score of 52.3, up 1.4 from yesterday. A real rate of 1.9% in the elevated band is the main driver, and NVDA's 2.1% one-day drop reinforces risk-off sentiment.",
  top_risk_drivers: [
    {
      claim:
        "The real rate rose to 1.9%, at the 72nd percentile over 5 years, pushing the macro dimension risk score to 62.",
      evidence_refs: [
        {
          dataset: "macro",
          path: "payload.rates[0].value",
          metric: "real_rate_dfii10",
          value: 1.9,
          updated_at: "2026-08-03T09:30:00Z",
        },
      ],
    },
  ],
  supporting_signals: [
    {
      claim: "NVDA fell 2.1% in a day, pressuring the memory complex.",
      evidence_refs: [
        {
          dataset: "equities",
          path: "payload.assets[0].change_1d",
          metric: "change_1d",
          value: -2.1,
          updated_at: "2026-08-03T10:00:00Z",
        },
      ],
    },
  ],
  contradicting_signals: [
    {
      claim: "Confidence of 0.72 with full data coverage.",
      evidence_refs: [
        {
          dataset: "risk",
          path: "payload.total_score",
          metric: "total_score",
          value: 52.3,
          updated_at: "2026-08-03T10:00:00Z",
        },
      ],
    },
  ],
  what_changed_today: ["Total risk score rose 1.4 from yesterday."],
  watch_next: ["Watch tomorrow's CPI for its impact on real rates."],
  bull_case: {
    title: "Bull case: rates fall below 1.5%",
    points: ["If inflation cools, real rates may decline."],
    evidence_refs: [
      {
        dataset: "macro",
        path: "payload.rates[0].value",
        metric: "real_rate_dfii10",
        value: 1.9,
        updated_at: "2026-08-03T09:30:00Z",
      },
    ],
  },
  base_case: {
    title: "Base case: stay cautious",
    points: ["The risk score oscillates between 45 and 60."],
    evidence_refs: [],
  },
  bear_case: {
    title: "Bear case: risk score breaks above 70",
    points: ["If NVDA falls more than 5%, breadth will deteriorate."],
    evidence_refs: [],
  },
  confidence: 0.72,
  evidence_refs: [
    {
      dataset: "risk",
      path: "payload.total_score",
      metric: "total_score",
      value: 52.3,
      updated_at: "2026-08-03T10:00:00Z",
    },
  ],
  data_freshness: "fresh",
};

export const riskHistory30dFixture = [
  { date: "2026-07-06", total_score: 48.1, risk_level: "caution", regime: "late_cycle", confidence: 0.7, dim_scores: { macro: 55.2, liquidity_credit: 30.1, equity_structure: 45.4, volatility: 40.2, cross_asset: 50.0, trend: 50.0 } },
  { date: "2026-07-13", total_score: 50.4, risk_level: "caution", regime: "late_cycle", confidence: 0.71, dim_scores: { macro: 57.0, liquidity_credit: 31.0, equity_structure: 47.0, volatility: 41.0, cross_asset: 50.0, trend: 49.0 } },
  { date: "2026-07-20", total_score: 49.2, risk_level: "caution", regime: "late_cycle", confidence: 0.72, dim_scores: { macro: 56.0, liquidity_credit: 30.0, equity_structure: 46.0, volatility: 39.0, cross_asset: 50.0, trend: 48.0 } },
  { date: "2026-07-27", total_score: 51.8, risk_level: "caution", regime: "late_cycle", confidence: 0.73, dim_scores: { macro: 58.0, liquidity_credit: 32.0, equity_structure: 48.0, volatility: 42.0, cross_asset: 50.0, trend: 49.0 } },
  { date: "2026-08-03", total_score: 52.3, risk_level: "caution", regime: "late_cycle", confidence: 0.72, dim_scores: { macro: 60.0, liquidity_credit: 33.0, equity_structure: 49.0, volatility: 43.0, cross_asset: 50.0, trend: 50.0 } },
];

export const marketHistory30dFixture = [
  { date: "2026-07-06", symbol: "SPY", close: 741.0 },
  { date: "2026-07-13", symbol: "SPY", close: 749.5 },
  { date: "2026-07-20", symbol: "SPY", close: 745.2 },
  { date: "2026-07-27", symbol: "SPY", close: 752.8 },
  { date: "2026-08-03", symbol: "SPY", close: 748.4 },
];

export const sourcesFixture = {
  schema_version: "1.0.0",
  updated_at: "2026-08-07T09:00:00Z",
  // #95: mirrors the current projection shape — each domain carries the derived fields
  // (status/reason/datasets) plus provider passthrough, exactly as sources.json is
  // rendered from the one outcomes record (#89/#101, economic domain per #94).
  domains: {
    market: {
      provider: "yfinance",
      used_fallback: false,
      from_cache: false,
      degraded: true,
      status: "degraded",
      reason: { code: "provider_http_error", detail: "yfinance: HTTP 429 rate limited" },
      datasets: ["equities", "sectors"],
    },
    macro: {
      provider: "fred",
      used_fallback: false,
      from_cache: false,
      degraded: false,
      status: "fresh",
      reason: { code: "ok", detail: "" },
      datasets: ["macro"],
    },
    crypto: {
      provider: "coingecko",
      used_fallback: false,
      from_cache: false,
      degraded: false,
      status: "fresh",
      reason: { code: "ok", detail: "" },
      datasets: ["crypto"],
    },
    calendar: {
      provider: "fmp",
      used_fallback: false,
      from_cache: false,
      degraded: false,
      status: "empty",
      reason: { code: "no_events_in_window", detail: "no events in the 14-day window" },
      datasets: ["calendar"],
    },
    economic: {
      provider: "fred_calendar",
      used_fallback: false,
      from_cache: false,
      degraded: false,
      status: "fresh",
      reason: { code: "ok", detail: "" },
      datasets: ["calendar"],
    },
    news: {
      provider: "rss_news",
      used_fallback: true,
      from_cache: false,
      degraded: true,
      status: "degraded",
      reason: { code: "provider_http_error", detail: "clschina: RSS HTTP 403" },
      datasets: ["news"],
    },
    a_share: {
      provider: "akshare",
      used_fallback: false,
      from_cache: false,
      degraded: true,
      status: "degraded",
      reason: { code: "all_providers_failed", detail: "akshare: RemoteDisconnected" },
      datasets: [],
    },
  },
};

export const freshnessFixture = {
  schema_version: "1.0.0",
  updated_at: "2026-08-07T09:00:00Z",
  // #95: the published reason is a {code, detail} pair from the closed vocabulary — no
  // literal "degraded" placeholders remain (E-1/#89). Every registered key appears.
  datasets: {
    equities: { status: "degraded", reason: { code: "provider_http_error", detail: "yfinance: HTTP 429 rate limited" }, updated_at: "2026-08-07T09:00:00Z" },
    sectors: { status: "degraded", reason: { code: "provider_http_error", detail: "yfinance: HTTP 429 rate limited" }, updated_at: "2026-08-07T09:00:00Z" },
    crypto: { status: "fresh", reason: { code: "ok", detail: "" }, updated_at: "2026-08-07T09:00:00Z" },
    macro: { status: "fresh", reason: { code: "ok", detail: "" }, updated_at: "2026-08-07T09:00:00Z" },
    calendar: { status: "empty", reason: { code: "no_events_in_window", detail: "no events in the 14-day window" }, updated_at: "2026-08-07T09:00:00Z" },
    news: { status: "degraded", reason: { code: "provider_http_error", detail: "clschina: RSS HTTP 403" }, updated_at: "2026-08-07T09:00:00Z" },
    risk: { status: "degraded", reason: { code: "input_dataset_unhealthy", detail: "equities degraded" }, updated_at: "2026-08-07T09:00:00Z" },
    dashboard: { status: "degraded", reason: { code: "input_dataset_unhealthy", detail: "equities degraded" }, updated_at: "2026-08-07T09:00:00Z" },
    factlayer: { status: "degraded", reason: { code: "input_dataset_unhealthy", detail: "equities degraded" }, updated_at: "2026-08-07T09:00:00Z" },
    analysis: { status: "fresh", reason: { code: "ok", detail: "" }, updated_at: "2026-08-07T09:00:00Z" },
    news_translations: { status: "fresh", reason: { code: "ok", detail: "" }, updated_at: "2026-08-07T09:00:00Z" },
  },
};

export const schemaVersionFixture = {
  schema_version: "1.0.0",
  updated_at: "2026-08-03T13:59:37Z",
};
