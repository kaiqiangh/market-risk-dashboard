import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { MacroEnvelope } from "@/schemas";
import { MacroIndicatorCard } from "@/components/macro/MacroIndicatorCard";
import { RateExpectationCard } from "@/components/macro/RateExpectationCard";
import { MacroChart } from "@/charts/MacroChart";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";

const SECTIONS = ["rates", "credit", "inflation", "labor", "liquidity", "fx"] as const;

/**
 * MacroPage: macro page (rates / credit / inflation / labor / liquidity / fx + FedWatch + charts).
 */
export default function MacroPage() {
  const { t } = useTranslation("macro");
  const macroQ = useDataset<MacroEnvelope>("macro");

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
          {/* Chart (merges rates + credit values) — open chart region, no card chrome */}
          <section className="border-t border-hairline pt-4">
            <h2 className="mb-2 text-sm font-medium text-foreground">{t("chart.title")}</h2>
            <MacroChart
                items={[...macroQ.data.payload.rates, ...macroQ.data.payload.credit]
                  .filter((ind) => ind.value !== null)
                  .map((ind) => ({ label: ind.label, value: ind.value as number, unit: ind.unit }))}
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
