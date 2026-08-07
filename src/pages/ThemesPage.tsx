import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { CommoditiesEnvelope, CryptoEnvelope, EquitiesEnvelope, SectorsEnvelope } from "@/schemas";
import { MemorySectorTable } from "@/components/equities/MemorySectorTable";
import { AssetCard } from "@/components/cross-asset/AssetCard";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { formatCompactNumber, formatRatio } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent } from "@/components/ui/Card";
import { dirTone, dirClasses } from "@/lib/riskColors";

/**
 * ThemesPage: themes page (semis / memory (incl. 11 A-shares) / commodities / crypto).
 * Shows degraded when T03 is degraded (A-share collection failure → notice + empty state).
 *
 * #93: the 20 themes render from sectors.json themes — labels via t(themes.<key>),
 * percentile_1y as a quintile band (or "warming up N/100" below min_obs), constituents as
 * symbol chips.
 *
 * #118: commodities (gold/silver/copper/oil) render from commodities.json — replacing the
 * old "Metals data not yet connected" placeholder.
 */

/** One theme card: label, 1d/1M changes, percentile band, constituent chips (#93). */
function ThemeCard({ theme }: { theme: { key: string; change_1d: number | null; change_1m: number | null; percentile_1y: number | null; percentile_1y_obs: number; constituents: string[] } }) {
  const { t } = useTranslation("themes");
  const dTone = dirTone(theme.change_1d);
  const pct = theme.percentile_1y;
  const band =
    pct === null
      ? null
      : pct < 20
        ? { label: "percentile.veryLow", cls: "text-muted-foreground" }
        : pct < 40
          ? { label: "percentile.low", cls: "text-muted-foreground" }
          : pct < 60
            ? { label: "percentile.normal", cls: "text-foreground" }
            : pct < 80
              ? { label: "percentile.high", cls: "text-foreground" }
              : { label: "percentile.veryHigh", cls: "text-foreground" };
  return (
    <Card data-testid={`theme-card-${theme.key}`}>
      <CardContent className="flex flex-col gap-2 p-3">
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate text-xs font-medium text-foreground">
            {t(`${theme.key}`, { defaultValue: theme.key })}
          </span>
          <span className={`shrink-0 text-xs font-semibold tabular-nums ${dirClasses(dTone).text}`}>
            {theme.change_1d === null ? t("common:data.na") : `${theme.change_1d > 0 ? "+" : ""}${theme.change_1d}%`}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
          <span>1M {theme.change_1m === null ? t("common:data.na") : `${theme.change_1m > 0 ? "+" : ""}${theme.change_1m}%`}</span>
          {band ? (
            <span className={band.cls}>{t(band.label)}</span>
          ) : theme.percentile_1y_obs > 0 ? (
            <span>{t("percentile.warming", { obs: theme.percentile_1y_obs })}</span>
          ) : null}
        </div>
        {theme.constituents.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {theme.constituents.slice(0, 8).map((sym) => (
              <span key={sym} className="rounded border border-hairline px-1 py-0.5 font-mono text-[9px] text-muted-foreground">
                {sym}
              </span>
            ))}
            {theme.constituents.length > 8 ? (
              <span className="px-0.5 text-[9px] text-muted-foreground">+{theme.constituents.length - 8}</span>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function ThemesPage() {
  const { t, i18n } = useTranslation("themes");
  const locale = i18n.language;
  const sectorsQ = useDataset<SectorsEnvelope>("sectors");
  const equitiesQ = useDataset<EquitiesEnvelope>("equities");
  const cryptoQ = useDataset<CryptoEnvelope>("crypto");
  const commoditiesQ = useDataset<CommoditiesEnvelope>("commodities");

  const themes = sectorsQ.data?.payload.themes ?? [];
  const sectors = sectorsQ.data?.payload.sectors ?? [];
  const cnAssets = equitiesQ.data?.payload.assets.filter((a) => a.market === "CN") ?? [];
  const memory = sectorsQ.data?.payload.memory ?? null;
  const cryptoAssets = cryptoQ.data?.payload.assets ?? [];
  const commodityAssets = commoditiesQ.data?.payload.assets ?? [];

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
                symbol={t(`${s.key}`, { defaultValue: s.key })}
                change1d={s.change_1d}
                sub={`1W ${s.change_1w === null ? t("common:data.na") : `${s.change_1w > 0 ? "+" : ""}${s.change_1w}%`}`}
              />
            ))}
          </div>
        ) : (
          <EmptyState title={t("section.empty")} />
        )}
      </section>

      {/* Memory (incl. 11 A-shares) */}
      <section className="border-t border-hairline pt-4" data-testid="section-memory">
        <MemorySectorTable assets={cnAssets} memory={memory} />
      </section>

      {/* Commodities (gold/silver/copper/oil, #118) */}
      <section className="border-t border-hairline pt-4" data-testid="section-metals">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("section.metals")}</h2>
        {commoditiesQ.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : commoditiesQ.isError ? (
          <ErrorState onRetry={commoditiesQ.refetch} />
        ) : commodityAssets.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {commodityAssets.map((c) => (
              <AssetCard
                key={c.symbol}
                symbol={c.symbol}
                name={locale === "en" ? c.name : (c.name_zh ?? c.name)}
                value={c.price}
                change1d={c.change_1d}
                sub={`1M ${c.change_1m === null ? t("common:data.na") : `${c.change_1m > 0 ? "+" : ""}${c.change_1m}%`}`}
              />
            ))}
          </div>
        ) : (
          <EmptyState title={t("metals.na")} message={t("metals.naHint")} />
        )}
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

      {/* Theme list (20 themes, #93) */}
      <section className="border-t border-hairline pt-4" data-testid="section-themes">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("section.themes")}</h2>
        {themes.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {themes.map((th) => (
              <ThemeCard key={th.key} theme={th} />
            ))}
          </div>
        ) : (
          <EmptyState title={t("section.empty")} />
        )}
      </section>
    </div>
  );
}
