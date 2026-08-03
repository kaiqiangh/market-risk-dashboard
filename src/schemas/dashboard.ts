import { z } from "zod";
import { datasetEnvelope } from "./envelope";
import { DriverContribution, MarketRegime, RiskModelResult } from "./risk";

/**
 * Dashboard aggregation schema (dashboard.json per architecture §3.6).
 * Registered in T04 (resolvable by DatasetClient); the Overview page combines
 * risk/crypto/equities/sectors/calendar/news directly for robustness and does not hard-depend on this file.
 * After the pipeline produces dashboard.json in T05, the homepage can seamlessly switch to the single-file aggregation.
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
