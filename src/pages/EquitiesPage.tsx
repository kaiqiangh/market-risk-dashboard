import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import { KEY_US_STOCKS } from "@/config/universe";
import type { EquitiesEnvelope, SectorsEnvelope } from "@/schemas";
import { EquityCard } from "@/components/equities/EquityCard";
import { MemorySectorTable } from "@/components/equities/MemorySectorTable";
import { AShareCard } from "@/components/equities/AShareCard";
import { AssetCard } from "@/components/cross-asset/AssetCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";

/**
 * EquitiesPage：股票页（Equity Monitor）。
 * 裁剪范围（G2）：Cross-Asset 卡片 + 4-5 只关键股（NVDA/AVGO/MU/AMD/TSLA）+ A 股存储。
 */
export default function EquitiesPage() {
  const { t, i18n } = useTranslation("equities");
  const locale = i18n.language;
  const equitiesQ = useDataset<EquitiesEnvelope>("equities");
  const sectorsQ = useDataset<SectorsEnvelope>("sectors");

  const usAssets =
    equitiesQ.data?.payload.assets.filter((a) => a.market === "US" && KEY_US_STOCKS.includes(a.symbol)) ?? [];
  const cnAssets = equitiesQ.data?.payload.assets.filter((a) => a.market === "CN") ?? [];
  const memory = sectorsQ.data?.payload.memory ?? null;

  // Cross-Asset 卡片：关键股 + 加密 + 板块代理
  const crossAssets = equitiesQ.data?.payload.assets.filter((a) => KEY_US_STOCKS.includes(a.symbol)) ?? [];

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        {equitiesQ.data ? <StatusBadge status={equitiesQ.data.freshness_status} withDescription /> : null}
      </header>

      {/* Cross-Asset 卡片 */}
      <Card>
        <CardHeader>
          <CardTitle>{t("section.crossAsset")}</CardTitle>
        </CardHeader>
        <CardContent>
          {equitiesQ.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : equitiesQ.isError ? (
            <ErrorState onRetry={equitiesQ.refetch} />
          ) : crossAssets.length > 0 ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5" data-testid="cross-asset-cards">
              {crossAssets.map((a) => (
                <AssetCard
                  key={a.symbol}
                  symbol={a.symbol}
                  name={locale.startsWith("zh") && a.name_zh ? a.name_zh : a.name}
                  value={a.price}
                  change1d={a.change_1d}
                  sub={a.currency}
                />
              ))}
            </div>
          ) : (
            <EmptyState title={t("section.empty")} />
          )}
        </CardContent>
      </Card>

      {/* 关键美股 */}
      <section data-testid="section-us">
        <h2 className="mb-2 text-sm font-semibold text-foreground">{t("section.us")}</h2>
        {equitiesQ.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : equitiesQ.isError ? (
          <ErrorState onRetry={equitiesQ.refetch} />
        ) : usAssets.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="us-equity-cards">
            {usAssets.map((a) => (
              <EquityCard key={a.symbol} asset={a} />
            ))}
          </div>
        ) : (
          <EmptyState title={t("section.empty")} />
        )}
      </section>

      {/* 存储板块 + A 股 */}
      <section data-testid="section-memory">
        <MemorySectorTable assets={cnAssets} memory={memory} />
      </section>

      {/* A 股卡片（移动端；长表格已在上方桌面表格，此处补卡片视图） */}
      {cnAssets.length > 0 ? (
        <section data-testid="section-ashare">
          <h2 className="mb-2 text-sm font-semibold text-foreground">{t("section.aShare")}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {cnAssets.map((a) => (
              <AShareCard key={a.symbol} asset={a} />
            ))}
          </div>
        </section>
      ) : null}

      {cnAssets.length === 0 ? (
        <p className="text-xs text-muted-foreground" data-testid="ashare-missing-note">
          {t("aShare.degraded")}
        </p>
      ) : null}
    </div>
  );
}
