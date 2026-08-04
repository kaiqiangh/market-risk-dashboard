import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { datasetClient } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDateTime } from "@/lib/format";
import { freshTone, freshClasses } from "@/lib/riskColors";

/**
 * StatusPage: system status page.
 * Data sources: metadata/sources.json (provider health) + metadata/freshness.json (five states)
 *        + metadata/schema-version.json (contract version).
 * Metadata is not an envelope; fetched with an explicit z.unknown() schema (DatasetClient third argument).
 */
interface SourcesMetadata {
  schema_version?: string;
  updated_at?: string;
  domains?: Record<string, unknown>;
}

interface FreshnessMetadata {
  schema_version?: string;
  datasets?: Record<string, { status?: string; reason?: string; updated_at?: string }>;
}

export default function StatusPage() {
  const { t, i18n } = useTranslation("status");
  const locale = i18n.language;

  const sourcesQ = useQuery({
    queryKey: ["metadata", "sources"],
    queryFn: () => datasetClient.fetch<SourcesMetadata>("sources", {}, z.unknown()),
    staleTime: 60_000,
    retry: 1,
  });

  const freshnessQ = useQuery({
    queryKey: ["metadata", "freshness"],
    queryFn: () => datasetClient.fetch<FreshnessMetadata>("freshness", {}, z.unknown()),
    staleTime: 60_000,
    retry: 1,
  });

  const schemaQ = useQuery({
    queryKey: ["metadata", "schema-version"],
    queryFn: () => datasetClient.fetch<{ schema_version?: string; updated_at?: string }>("schema-version", {}, z.unknown()),
    staleTime: 60_000,
    retry: 1,
  });

  const datasets = freshnessQ.data?.datasets ?? {};

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
      </header>

      {/* Meta info */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>{t("meta.schemaVersion")}</CardTitle>
          </CardHeader>
          <CardContent>
            {schemaQ.isLoading ? (
              <Skeleton className="h-6 w-24" />
            ) : schemaQ.data?.schema_version ? (
              <p className="font-mono text-lg font-semibold">{schemaQ.data.schema_version}</p>
            ) : (
              <p className="text-sm text-muted-foreground">{t("common:data.na")}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("meta.sourcesUpdated")}</CardTitle>
          </CardHeader>
          <CardContent>
            {sourcesQ.isLoading ? (
              <Skeleton className="h-6 w-32" />
            ) : sourcesQ.data?.updated_at ? (
              <p className="text-sm tabular-nums">{formatDateTime(sourcesQ.data.updated_at, locale)}</p>
            ) : (
              <p className="text-sm text-muted-foreground">{t("common:data.na")}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("meta.datasetCount")}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-semibold tabular-nums">{Object.keys(datasets).length}</p>
          </CardContent>
        </Card>
      </div>

      {/* Dataset five states (hairline section, not a card) */}
      <section className="border-t border-hairline pt-4">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("freshness.title")}</h2>
        {freshnessQ.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : freshnessQ.isError ? (
            <ErrorState onRetry={freshnessQ.refetch} />
          ) : Object.keys(datasets).length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-xs">
                <thead>
                  <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 pr-2 font-medium">{t("freshness.dataset")}</th>
                    <th className="py-1.5 pr-2 font-medium">{t("freshness.status")}</th>
                    <th className="py-1.5 pr-2 font-medium">{t("freshness.updatedAt")}</th>
                    <th className="py-1.5 font-medium">{t("freshness.reason")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(datasets).map(([key, info]) => {
                    const status = (info?.status ?? "missing") as
                      | "fresh"
                      | "delayed"
                      | "stale"
                      | "missing"
                      | "degraded";
                    return (
                      <tr key={key} className="border-b border-border/50 last:border-0">
                        <td className="py-1.5 pr-2">{t(`datasets.${key}`, { defaultValue: key })}</td>
                        <td className="py-1.5 pr-2">
                          <StatusBadge status={status} />
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">
                          {info?.updated_at ? formatDateTime(info.updated_at, locale) : t("common:data.na")}
                        </td>
                        <td className="py-1.5 text-muted-foreground">{info?.reason ?? t("common:data.na")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title={t("freshness.none")} />
          )}
      </section>

      {/* Provider health (hairline section, not a card) */}
      <section className="border-t border-hairline pt-4">
        <h2 className="mb-2 text-sm font-medium text-foreground">{t("providers.title")}</h2>
        {sourcesQ.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : sourcesQ.isError ? (
            <ErrorState onRetry={sourcesQ.refetch} />
          ) : sourcesQ.data?.domains && Object.keys(sourcesQ.data.domains).length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-xs">
                <thead>
                  <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                    <th className="py-1.5 pr-2 font-medium">{t("providers.domain")}</th>
                    <th className="py-1.5 pr-2 font-medium">{t("providers.provider")}</th>
                    <th className="py-1.5 font-medium">{t("providers.error")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(sourcesQ.data.domains).map(([domain, raw]) => {
                    const info = (raw ?? {}) as Record<string, unknown>;
                    const degraded = Boolean(info.degraded);
                    const usedFallback = Boolean(info.used_fallback);
                    const fromCache = Boolean(info.from_cache);
                    const error = typeof info.error === "string" ? (info.error as string) : null;
                    const provider = typeof info.provider === "string" ? (info.provider as string) : null;
                    // #65: show the resolved provider and how it was served (fallback/cache)
                    // instead of bare Yes/No booleans.
                    const served = provider ?? t("common:data.na");
                    const annotation = fromCache
                      ? ` · ${t("providers.cache")}`
                      : usedFallback
                        ? ` · ${t("providers.fallback")}`
                        : "";
                    return (
                      <tr key={domain} className="border-b border-border/50 last:border-0">
                        <td className="py-1.5 pr-2">{domain}</td>
                        <td className="py-1.5 pr-2">
                          <span className="font-mono">{served}</span>
                          {annotation ? (
                            <span className="ml-1 text-[10px] text-muted-foreground">{annotation}</span>
                          ) : null}
                        </td>
                        <td className="py-1.5">
                          {degraded ? (
                            <span className={freshClasses(freshTone("degraded")).text}>
                              {t("providers.degraded")}
                            </span>
                          ) : error ? (
                            <span className="max-w-[320px] truncate font-mono text-[10px] text-risk-severe" title={error}>
                              {error}
                            </span>
                          ) : (
                            <span className="text-risk-low">{t("providers.ok")}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title={t("providers.none")} />
          )}
      </section>
    </div>
  );
}
