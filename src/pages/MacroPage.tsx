import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { MacroEnvelope } from "@/schemas";
import { MacroIndicatorCard } from "@/components/macro/MacroIndicatorCard";
import { RateExpectationCard } from "@/components/macro/RateExpectationCard";
import { MacroChart } from "@/charts/MacroChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
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
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        {macroQ.data ? <StatusBadge status={macroQ.data.freshness_status} withDescription /> : null}
      </header>

      {macroQ.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : macroQ.isError ? (
        <ErrorState onRetry={macroQ.refetch} />
      ) : macroQ.data ? (
        <>
          {/* Chart (merges rates + credit values) */}
          <Card>
            <CardHeader>
              <CardTitle>{t("chart.title")}</CardTitle>
            </CardHeader>
            <CardContent>
              <MacroChart
                items={[...macroQ.data.payload.rates, ...macroQ.data.payload.credit]
                  .filter((ind) => ind.value !== null)
                  .map((ind) => ({ label: ind.label, value: ind.value as number, unit: ind.unit }))}
              />
            </CardContent>
          </Card>

          {/* Sectioned indicator cards */}
          <div className="flex flex-col gap-4">
            {SECTIONS.map((section) => {
              const indicators = macroQ.data?.payload[section] ?? [];
              if (indicators.length === 0) {
                return (
                  <section key={section} data-testid={`section-${section}`}>
                    <h2 className="mb-2 text-sm font-semibold text-foreground">{t(`section.${section}`)}</h2>
                    <EmptyState title={t("section.empty")} />
                  </section>
                );
              }
              return (
                <section key={section} data-testid={`section-${section}`}>
                  <h2 className="mb-2 text-sm font-semibold text-foreground">{t(`section.${section}`)}</h2>
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
          <section data-testid="section-fedwatch">
            <h2 className="mb-2 text-sm font-semibold text-foreground">{t("fedwatch.title")}</h2>
            <RateExpectationCard fedwatch={macroQ.data.payload.fedwatch} />
          </section>
        </>
      ) : (
        <EmptyState title={t("common:empty.title")} />
      )}
    </div>
  );
}
