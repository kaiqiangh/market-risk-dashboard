import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { RiskEnvelope } from "@/schemas";
import { RiskDimensionBreakdown } from "@/components/risk/RiskDimensionBreakdown";
import { RiskScoreGauge } from "@/components/risk/RiskScoreGauge";
import { TopDrivers } from "@/components/risk/TopDrivers";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";

/**
 * RiskLabPage: risk lab (6-dimension risk model breakdown + weights + confidence + disclaimer).
 */
export default function RiskLabPage() {
  const { t } = useTranslation("risk");
  const riskQ = useDataset<RiskEnvelope>("risk");

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        {riskQ.data ? <span className="ml-auto"><StatusBadge status={riskQ.data.freshness_status} fromCache={riskQ.data.provenance?.from_cache} withDescription /></span> : null}
      </header>

      {riskQ.isLoading ? (
        <Skeleton className="h-96 w-full" />
      ) : riskQ.isError ? (
        <ErrorState onRetry={riskQ.refetch} />
      ) : riskQ.data ? (
        <>
          <section className="grid grid-cols-1 gap-4 md:grid-cols-3" data-testid="risklab-summary">
            <div className="md:col-span-1">
              <RiskScoreGauge
                score={riskQ.data.payload.total_score}
                level={riskQ.data.payload.risk_level}
                trend1d={riskQ.data.payload.trend_1d}
                trend1w={riskQ.data.payload.trend_1w}
                trend1m={riskQ.data.payload.trend_1m}
                confidence={riskQ.data.payload.confidence}
              />
            </div>
            <div className="md:col-span-2">
              <TopDrivers drivers={riskQ.data.payload.top_drivers} />
            </div>
          </section>

          <section className="border-t border-hairline pt-4">
            <RiskDimensionBreakdown result={riskQ.data.payload} />
          </section>
        </>
      ) : (
        <EmptyState title={t("common:empty.title")} />
      )}
    </div>
  );
}
