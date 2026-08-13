import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { datasetClient } from "@/lib/api";
import { useDataset } from "@/hooks/useDataset";
import type { MacroEnvelope } from "@/schemas";
import { MacroIndicatorCard } from "@/components/macro/MacroIndicatorCard";
import { RateExpectationCard } from "@/components/macro/RateExpectationCard";
import { MacroChart } from "@/charts/MacroChart";
import { MacroHistoryChart, type MacroBundle } from "@/charts/MacroHistoryChart";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";

// #96 (uses #84): seven groups incl. the new `volatility` (VIX is an implied-volatility
// index, not a rate) — mirrors risk_model.yaml's dimensions.
const SECTIONS = ["rates", "credit", "volatility", "inflation", "labor", "liquidity", "fx"] as const;
type MacroGroup = (typeof SECTIONS)[number];

/** history/macro/{group}.{slice}.json — sparse column-oriented per-series history (#84 §3). */
const MacroBundleSchema = z.record(z.object({ d: z.array(z.string()), v: z.array(z.number()) }));

/**
 * MacroPage: macro page (rates / credit / volatility / inflation / labor / liquidity / fx
 * + FedWatch + cross-sectional chart + per-group 30d history chart).
 */
export default function MacroPage() {
  const { t } = useTranslation("macro");
  const macroQ = useDataset<MacroEnvelope>("macro");
  const [historyGroup, setHistoryGroup] = useState<MacroGroup>("fx");
  const [historySlice, setHistorySlice] = useState<"30d" | "90d">("30d");

  const historyQ = useQuery({
    queryKey: ["history", "macro", historyGroup, historySlice],
    queryFn: () => datasetClient.fetch<MacroBundle>("macro", { slice: `${historyGroup}.${historySlice}` }, MacroBundleSchema),
    staleTime: 60_000,
    retry: 1,
  });

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        {macroQ.data ? <span className="ml-auto"><StatusBadge status={macroQ.data.freshness_status} fromCache={macroQ.data.provenance?.from_cache} withDescription /></span> : null}
      </header>

      {macroQ.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : macroQ.isError ? (
        <ErrorState onRetry={macroQ.refetch} />
      ) : macroQ.data ? (
        <>
          {/* Cross-sectional chart (market pricing: rates + credit + volatility) — open region */}
          <section className="border-t border-hairline pt-4">
            <h2 className="mb-2 text-sm font-medium text-foreground">{t("chart.title")}</h2>
            <MacroChart
                // Cross-sectional market pricing stays rates + credit: VIX (~17) on the
                // same linear axis would flatten the % bars (review, #96) — volatility
                // renders in its own section and history instead.
                items={[...macroQ.data.payload.rates, ...macroQ.data.payload.credit]
                  .filter((ind) => ind.value !== null)
                  .map((ind) => ({
                    label: t(`indicatorNames.${ind.key}`, { defaultValue: t("indicatorNames.unknown") }),
                    value: ind.value as number,
                    unit: ind.unit,
                  }))}
              />
          </section>

          {/* Sectioned indicator cards */}
          <div className="flex flex-col gap-4 border-t border-hairline pt-4">
            {SECTIONS.map((section) => {
              const indicators = macroQ.data?.payload[section] ?? [];
              if (indicators.length === 0) {
                return (
                  <section key={section} data-testid={`section-${section}`}>
                    <h2 className="mb-2 text-sm font-medium text-foreground">{t(`section.${section}`)}</h2>
                    <EmptyState title={t("section.empty")} />
                  </section>
                );
              }
              return (
                <section key={section} data-testid={`section-${section}`}>
                  <h2 className="mb-2 text-sm font-medium text-foreground">{t(`section.${section}`)}</h2>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {indicators.map((ind) => (
                      <MacroIndicatorCard key={ind.key} indicator={ind} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>

          {/* Per-group 30d history (#96: history stored in the #84 shape, charted here) */}
          <section className="border-t border-hairline pt-4" data-testid="section-history">
            <h2 className="mb-2 text-sm font-medium text-foreground">{t("history.title")}</h2>
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              {SECTIONS.map((group) => (
                <button
                  key={group}
                  type="button"
                  onClick={() => setHistoryGroup(group)}
                  className={`rounded-full border px-2.5 py-0.5 text-xs min-h-[28px] transition-colors ${
                    historyGroup === group
                      ? "border-fresh-ok/40 bg-fresh-ok/10 text-fresh-ok"
                      : "border-hairline text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t(`section.${group}`)}
                </button>
              ))}
              <span className="ml-auto flex gap-1.5">
                {(["30d", "90d"] as const).map((slice) => (
                  <button
                    key={slice}
                    type="button"
                    onClick={() => setHistorySlice(slice)}
                    className={`rounded-full border px-2.5 py-0.5 text-xs min-h-[28px] transition-colors ${
                      historySlice === slice
                        ? "border-fresh-ok/40 bg-fresh-ok/10 text-fresh-ok"
                        : "border-hairline text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {slice}
                  </button>
                ))}
              </span>
            </div>
            {historyQ.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : historyQ.isError ? (
              <ErrorState onRetry={historyQ.refetch} />
            ) : historyQ.data ? (
              <MacroHistoryChart bundle={historyQ.data} />
            ) : (
              <EmptyState title={t("history.empty")} />
            )}
          </section>

          {/* FedWatch */}
          <section className="border-t border-hairline pt-4" data-testid="section-fedwatch">
            <h2 className="mb-2 text-sm font-medium text-foreground">{t("fedwatch.title")}</h2>
            <RateExpectationCard fedwatch={macroQ.data.payload.fedwatch} />
          </section>
        </>
      ) : (
        <EmptyState title={t("common:empty.title")} />
      )}
    </div>
  );
}
