import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { datasetClient } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDateTime } from "@/lib/format";
import { freshnessTone, toneClasses } from "@/lib/riskColors";

/**
 * StatusPage：系统状态页。
 * 数据源：metadata/sources.json（Provider 健康）+ metadata/freshness.json（五态）
 *        + metadata/schema-version.json（契约版本）。
 * 元数据非 envelope，用 z.unknown() 显式 schema 拉取（DatasetClient 第三参）。
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
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
      </header>

      {/* 元信息 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
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

      {/* 数据集五态 */}
      <Card>
        <CardHeader>
          <CardTitle>{t("freshness.title")}</CardTitle>
        </CardHeader>
        <CardContent>
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
        </CardContent>
      </Card>

      {/* Provider 健康 */}
      <Card>
        <CardHeader>
          <CardTitle>{t("providers.title")}</CardTitle>
        </CardHeader>
        <CardContent>
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
                    <th className="py-1.5 pr-2 font-medium">{t("providers.fallback")}</th>
                    <th className="py-1.5 pr-2 font-medium">{t("providers.cache")}</th>
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
                    return (
                      <tr key={domain} className="border-b border-border/50 last:border-0">
                        <td className="py-1.5 pr-2">{domain}</td>
                        <td className="py-1.5 pr-2">{typeof info.provider === "string" ? info.provider : t("common:data.na")}</td>
                        <td className="py-1.5 pr-2">
                          <Badge variant={usedFallback ? "caution" : "low"} className="px-1.5 py-0 text-[10px]">
                            {usedFallback ? t("providers.yes") : t("providers.no")}
                          </Badge>
                        </td>
                        <td className="py-1.5 pr-2">
                          <Badge variant={fromCache ? "caution" : "secondary"} className="px-1.5 py-0 text-[10px]">
                            {fromCache ? t("providers.yes") : t("providers.no")}
                          </Badge>
                        </td>
                        <td className="py-1.5">
                          {degraded ? (
                            <span className={`text-risk-caution ${toneClasses(freshnessTone("degraded")).text}`}>
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
        </CardContent>
      </Card>
    </div>
  );
}
