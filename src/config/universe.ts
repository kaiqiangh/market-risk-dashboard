/**
 * 前端镜像资产池（架构 §8.10/§8.11，与 config/universe.yaml 对应）。
 * 展示用：筛选卡片顺序、主题分组、A 股名称。数据值一律来自 public/data（唯一事实源）。
 */

/** 美股关键池（MVP 冻结 G2）：Cross-Asset 卡片 + 卡片级指标。 */
export const KEY_US_STOCKS: readonly string[] = ["NVDA", "AVGO", "MU", "AMD", "TSLA"];

/** A 股存储池（建议代码，以 universe.yaml 为唯一事实源，T03 实际校验）。 */
export const A_SHARE_STOCKS: readonly { symbol: string; name: string }[] = [
  { symbol: "603986.SH", name: "兆易创新" },
  { symbol: "301308.SZ", name: "江波龙" },
  { symbol: "688525.SH", name: "佰维存储" },
  { symbol: "000021.SZ", name: "深科技" },
  { symbol: "300223.SZ", name: "北京君正" },
  { symbol: "001309.SZ", name: "德明利" },
  { symbol: "300475.SZ", name: "香农芯创" },
  { symbol: "688008.SH", name: "澜起科技" },
  { symbol: "600584.SH", name: "长电科技" },
  { symbol: "002156.SZ", name: "通富微电" },
];

/** 加密观察池。 */
export const CRYPTO_SYMBOLS: readonly string[] = ["BTC", "ETH", "SOL"];

/** 跨资产热力矩阵（category → 资产）。category 用 i18n 渲染，这里只定义 key。 */
export const HEATMAP_CATEGORIES: readonly { category: string; assets: readonly string[] }[] = [
  { category: "equities.us", assets: ["NVDA", "AVGO", "MU", "AMD", "TSLA"] },
  { category: "equities.memory", assets: ["603986.SH", "301308.SZ", "688525.SH", "000021.SZ"] },
  { category: "crypto.crypto", assets: ["BTC", "ETH", "SOL"] },
];
