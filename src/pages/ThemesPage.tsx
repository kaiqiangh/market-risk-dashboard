import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { CryptoEnvelope, EquitiesEnvelope, SectorsEnvelope } from "@/schemas";
import { MemorySectorTable } from "@/components/equities/MemorySectorTable";
import { AssetCard } from "@/components/cross-asset/AssetCard";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { formatCompactNumber, formatRatio } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

/**
 * ThemesPage: themes page (semis / memory (incl. 10 A-shares) / metals / crypto).
 * Shows degraded when T03 is degraded (A-share collection failure → notice + empty state).
 */
export default function ThemesPage() {
  const { t, i18n } = useTranslation("themes");
  const locale = i18n.language;
  const sectorsQ = useDataset<SectorsEnvelope>("sectors");
  const equitiesQ = useDataset<EquitiesEnvelope>("equities");
  const cryptoQ = useDataset<CryptoEnvelope>("crypto");

  const themes = sectorsQ.data?.payload.themes ?? [];
  const sectors = sectorsQ.data?.payload.sectors ?? [];
  const cnAssets = equitiesQ.data?.payload.assets.filter((a) => a.market === "CN") ?? [];
  const memory = sectorsQ.data?.payload.memory ?? null;
  const cryptoAssets = cryptoQ.data?.payload.assets ?? [];

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        {sectorsQ.data ? <span className="ml-auto"><StatusBadge status={sectorsQ.data.freshness_status} fromCache={sectorsQ.data.provenance?.from_cache} withDescription /></span> : null}
      </header>

      {/* Semiconductors */}
      <section className="border-t border-hairline pt-4" data-testid="section-semis">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("section.semis")}</h2>
        {sectorsQ.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : sectorsQ.isError ? (
          <ErrorState onRetry={sectorsQ.refetch} />
        ) : sectors.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {sectors.map((s) => (
              <AssetCard
                key={s.key}
                symbol={locale.startsWith("zh") && s.label_zh ? s.label_zh : s.label}
                change1d={s.change_1d}
                sub={`1W ${s.change_1w === null ? t("common:data.na") : `${s.change_1w > 0 ? "+" : ""}${s.change_1w}%`}`}
              />
            ))}
          </div>
        ) : (
          <EmptyState title={t("section.empty")} />
        )}
      </section>

      {/* Memory (incl. 10 A-shares) */}
      <section className="border-t border-hairline pt-4" data-testid="section-memory">
        <MemorySectorTable assets={cnAssets} memory={memory} />
      </section>

      {/* Metals (no dedicated data source in MVP, marked NA; proxied via sectors/themes per architecture) */}
      <section className="border-t border-hairline pt-4" data-testid="section-metals">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("section.metals")}</h2>
        <EmptyState title={t("metals.na")} message={t("metals.naHint")} />
      </section>

      {/* Crypto */}
      <section className="border-t border-hairline pt-4" data-testid="section-crypto">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("section.crypto")}</h2>
        {cryptoQ.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : cryptoQ.isError ? (
          <ErrorState onRetry={cryptoQ.refetch} />
        ) : cryptoAssets.length > 0 ? (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {cryptoQ.data?.payload.market_cap_total !== null &&
              cryptoQ.data?.payload.market_cap_total !== undefined ? (
                <span>
                  {t("crypto.marketCap")}:{" "}
                  <span className="font-semibold text-foreground">
                    {formatCompactNumber(cryptoQ.data.payload.market_cap_total, locale)}
                  </span>
                </span>
              ) : null}
              {cryptoQ.data?.payload.btc_dominance !== null && cryptoQ.data?.payload.btc_dominance !== undefined ? (
                <span>
                  {t("crypto.dominance")}:{" "}
                  <span className="font-semibold text-foreground">
                    {formatRatio(cryptoQ.data.payload.btc_dominance, locale)}
                  </span>
                </span>
              ) : null}
              {cryptoQ.data?.payload.sentiment ? (
                <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                  {t(`crypto.${cryptoQ.data.payload.sentiment}`)}
                </Badge>
              ) : null}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {cryptoAssets.map((c) => (
                <AssetCard
                  key={c.symbol}
                  symbol={c.symbol}
                  name={c.name}
                  value={c.price}
                  change1d={c.change_1d}
                  sub={t("crypto.volume24h")}
                />
              ))}
            </div>
          </>
        ) : (
          <EmptyState title={t("section.empty")} />
        )}
      </section>

      {/* Theme list */}
      <section className="border-t border-hairline pt-4" data-testid="section-themes">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("section.themes")}</h2>
        {themes.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {themes.map((th) => (
              <AssetCard
                key={th.key}
                symbol={locale.startsWith("zh") && th.label_zh ? th.label_zh : th.label}
                change1d={th.change_1d}
                sub={`1M ${th.change_1m === null ? t("common:data.na") : `${th.change_1m > 0 ? "+" : ""}${th.change_1m}%`}`}
              />
            ))}
          </div>
        ) : (
          <EmptyState title={t("section.empty")} />
        )}
      </section>
    </div>
  );
}
