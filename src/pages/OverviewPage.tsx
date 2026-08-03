import { useTranslation } from "react-i18next";
import { ArrowUpRight, CalendarClock, Layers } from "lucide-react";
import { useDataset } from "@/hooks/useDataset";
import { RiskTrendSlice } from "@/schemas/history";
import type {
  AnalysisDataset,
  CalendarEnvelope,
  CryptoEnvelope,
  EquitiesEnvelope,
  NewsEnvelope,
  RiskEnvelope,
  SectorsEnvelope,
} from "@/schemas";
import { RiskScoreGauge } from "@/components/risk/RiskScoreGauge";
import { RegimeCard } from "@/components/risk/RegimeCard";
import { TopDrivers } from "@/components/risk/TopDrivers";
import { AssetHeatmapView } from "@/components/cross-asset/AssetHeatmapView";
import { RiskTrendChart } from "@/charts/RiskTrendChart";
import { NewsCard } from "@/components/news/NewsCard";
import { EventCard } from "@/components/calendar/EventCard";
import { AIBrief } from "@/components/ai/AIBrief";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { changeTone, toneClasses } from "@/lib/riskColors";
import { formatChange } from "@/lib/format";
import type { HeatmapCell } from "@/charts/AssetHeatmap";

/**
 * OverviewPage: homepage (PRD §22.3 layout).
 * Data sources: risk.json (risk score / regime / drivers) + history/risk/30d.json (trend)
 *           + crypto/equities/sectors (cross-asset heatmap) + calendar (catalysts)
 *           + news (important news) + analysis.{lang}.json (AI brief).
 * Robustness: does not depend on dashboard.json until it is produced (switchable after the T05 aggregation).
 */
export default function OverviewPage() {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;

  const riskQ = useDataset<RiskEnvelope>("risk");
  const trendQ = useDataset<RiskTrendSlice>("risk", { slice: "30d" }, RiskTrendSlice);
  const cryptoQ = useDataset<CryptoEnvelope>("crypto");
  const equitiesQ = useDataset<EquitiesEnvelope>("equities");
  const sectorsQ = useDataset<SectorsEnvelope>("sectors");
  const calendarQ = useDataset<CalendarEnvelope>("calendar");
  const newsQ = useDataset<NewsEnvelope>("news");
  const analysisQ = useDataset<AnalysisDataset>("analysis", {
    lang: locale === "en" ? "en" : "zh-CN",
  });

  // Build cross-asset heatmap cells
  const heatmapCells: HeatmapCell[] = [];
  if (equitiesQ.data) {
    for (const a of equitiesQ.data.payload.assets) {
      heatmapCells.push({ asset: a.symbol, category: t("heatmap.catEquities"), change1d: a.change_1d });
    }
  }
  if (cryptoQ.data) {
    for (const a of cryptoQ.data.payload.assets) {
      heatmapCells.push({ asset: a.symbol, category: t("heatmap.catCrypto"), change1d: a.change_1d });
    }
  }
  if (sectorsQ.data) {
    for (const s of sectorsQ.data.payload.sectors) {
      heatmapCells.push({ asset: s.label_zh ?? s.label, category: t("heatmap.catSectors"), change1d: s.change_1d });
    }
    for (const th of sectorsQ.data.payload.themes) {
      heatmapCells.push({ asset: th.label_zh ?? th.label, category: t("heatmap.catThemes"), change1d: th.change_1d });
    }
  }

  // Upcoming catalysts (top 5 by ascending time)
  const nowIso = new Date().toISOString();
  const catalysts =
    calendarQ.data
      ? calendarQ.data.payload.events
          .filter((ev) => ev.datetime >= nowIso)
          .sort((a, b) => a.datetime.localeCompare(b.datetime))
          .slice(0, 5)
      : [];

  const topNews = newsQ.data ? [...newsQ.data.payload.items].sort((a, b) => b.importance - a.importance).slice(0, 4) : [];

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </header>

      {/* Risk conclusion first: Risk Score + Regime + Top Drivers */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="risk-conclusion">
        {riskQ.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : riskQ.isError ? (
          <ErrorState onRetry={riskQ.refetch} className="md:col-span-2 xl:col-span-3" />
        ) : riskQ.data ? (
          <>
            <RiskScoreGauge
              score={riskQ.data.payload.total_score}
              level={riskQ.data.payload.risk_level}
              trend1d={riskQ.data.payload.trend_1d}
              trend1w={riskQ.data.payload.trend_1w}
              trend1m={riskQ.data.payload.trend_1m}
              confidence={riskQ.data.payload.confidence}
              disclaimer={riskQ.data.payload.disclaimer}
            />
            <RegimeCard regime={riskQ.data.payload.regime} evidence={riskQ.data.payload.regime_evidence} />
            <TopDrivers drivers={riskQ.data.payload.top_drivers} />
          </>
        ) : (
          <EmptyState className="md:col-span-2 xl:col-span-3" />
        )}
        {riskQ.data ? (
          <div className="md:col-span-2 xl:col-span-3 -mt-2">
            <StatusBadge status={riskQ.data.freshness_status} withDescription />
          </div>
        ) : null}
      </section>

      {/* Cross-Asset Heatmap */}
      <section>
        {heatmapCells.length > 0 ? (
          <AssetHeatmapView cells={heatmapCells} />
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>{t("heatmap.title")}</CardTitle>
            </CardHeader>
            <CardContent>
              <EmptyState title={t("heatmap.empty")} />
            </CardContent>
          </Card>
        )}
      </section>

      {/* Market Trend + Upcoming Catalysts */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("trend.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            {trendQ.isLoading ? (
              <Skeleton className="h-64 w-full" />
            ) : trendQ.isError ? (
              <ErrorState onRetry={trendQ.refetch} />
            ) : trendQ.data && trendQ.data.length > 0 ? (
              <RiskTrendChart points={trendQ.data} />
            ) : (
              <EmptyState title={t("trend.empty")} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarClock className="h-4 w-4 text-muted-foreground" aria-hidden />
              {t("catalysts.title")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {calendarQ.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : calendarQ.isError ? (
              <ErrorState onRetry={calendarQ.refetch} />
            ) : catalysts.length > 0 ? (
              <div className="flex flex-col gap-2" data-testid="catalysts">
                {catalysts.map((ev) => (
                  <EventCard key={ev.id} event={ev} />
                ))}
              </div>
            ) : (
              <EmptyState title={t("catalysts.none")} />
            )}
          </CardContent>
        </Card>
      </section>

      {/* Sector Performance + Important News */}
      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-muted-foreground" aria-hidden />
              {t("sectors.title")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {sectorsQ.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : sectorsQ.isError ? (
              <ErrorState onRetry={sectorsQ.refetch} />
            ) : sectorsQ.data && sectorsQ.data.payload.sectors.length > 0 ? (
              <div className="flex flex-col gap-1.5" data-testid="sector-performance">
                {sectorsQ.data.payload.sectors.map((s) => {
                  const tone = changeTone(s.change_1d);
                  const classes = toneClasses(tone);
                  const label = locale.startsWith("zh") && s.label_zh ? s.label_zh : s.label;
                  return (
                    <div key={s.key} className="flex items-center justify-between rounded-md bg-muted/40 px-3 py-2">
                      <span className="text-sm text-foreground">{label}</span>
                      <span className={`text-sm font-semibold tabular-nums ${classes.text}`}>
                        {s.change_1d === null ? t("common:data.na") : formatChange(s.change_1d, locale)}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState title={t("sectors.none")} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ArrowUpRight className="h-4 w-4 text-muted-foreground" aria-hidden />
              {t("news.title")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {newsQ.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : newsQ.isError ? (
              <ErrorState onRetry={newsQ.refetch} />
            ) : topNews.length > 0 ? (
              <div className="flex flex-col gap-2" data-testid="important-news">
                {topNews.map((item) => (
                  <NewsCard key={item.id} item={item} />
                ))}
              </div>
            ) : (
              <EmptyState title={t("news.none")} />
            )}
          </CardContent>
        </Card>
      </section>

      {/* AI Market Brief */}
      <section>
        <AIBrief analysis={analysisQ.data} loading={analysisQ.isLoading} error={analysisQ.isError} />
      </section>
    </div>
  );
}
