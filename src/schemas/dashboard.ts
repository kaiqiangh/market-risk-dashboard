import { z } from "zod";
import { datasetEnvelope } from "./envelope";
import { DriverContribution, MarketRegime, RiskModelResult } from "./risk";

/**
 * 首页聚合 schema（架构 §3.6 的 dashboard.json）。
 * T04 先注册（DatasetClient 可解析）；Overview 页为稳健起见直接组合
 * risk/crypto/equities/sectors/calendar/news 渲染，不强制依赖本文件。
 * T05 管道产出 dashboard.json 后首页可无缝切换为单文件聚合。
 */
export const DashboardPayload = z
  .object({
    risk: RiskModelResult,
    regime: MarketRegime,
    top_drivers: z.array(DriverContribution),
    cross_asset: z
      .array(
        z
          .object({
            asset: z.string().min(1),
            category: z.string().min(1),
            change_1d: z.number().finite().nullable(),
          })
          .strict(),
      )
      .default([]),
    catalysts: z.array(z.record(z.unknown())).default([]),
    sector_performance: z.array(z.record(z.unknown())).default([]),
  })
  .strict();

export const DashboardEnvelope = datasetEnvelope(DashboardPayload);

export type DashboardPayload = z.infer<typeof DashboardPayload>;
export type DashboardEnvelope = z.infer<typeof DashboardEnvelope>;
