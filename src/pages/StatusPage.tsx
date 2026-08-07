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
import { FreshnessDocument, SourcesDocument, utcDateTime, type DomainStatus } from "@/schemas";

/**
 * StatusPage: system status page — the page whose job is truthfulness, so it validates
 * its inputs like every other page (#95): the metadata documents are parsed through the
 * SAME generated contracts the pipeline publishes (SourcesDocument / FreshnessDocument),
 * not `z.unknown()` casts. A published reason is a {code, detail} pair from the closed
 * vocabulary: the code is translated, `detail` is operator-facing English shown verbatim
 * on a secondary monospace line (and is the one field the pipeline redacts at the error
 * boundary, #92).
 */

/** Provider-domain entry. The DomainStatus contract declares the derived fields and
 * permits the rest as passthrough (used_fallback/from_cache are provider-added). The
 * provider error text deliberately has NO second channel here: reason.detail is the one
 * redacted field that may carry provider text (#92/#89), so the table renders only that. */
type DomainEntry = DomainStatus & {
  used_fallback?: boolean;
  from_cache?: boolean;
};

/** schema-version.json has no pydantic counterpart (tiny, self-describing) — an explicit
 * schema instead of z.unknown() so a shape change fails loudly on this page too. */
const SchemaVersion = z.object({
  schema_version: z.string().min(1),
  updated_at: utcDateTime.optional(),
});

export default function StatusPage() {
  const { t, i18n } = useTranslation("status");
  const locale = i18n.language;

  const sourcesQ = useQuery({
    queryKey: ["metadata", "sources"],
    queryFn: () => datasetClient.fetch<z.infer<typeof SourcesDocument>>("sources", {}, SourcesDocument),
    staleTime: 60_000,
    retry: 1,
  });

  const freshnessQ = useQuery({
    queryKey: ["metadata", "freshness"],
    queryFn: () => datasetClient.fetch<z.infer<typeof FreshnessDocument>>("freshness", {}, FreshnessDocument),
    staleTime: 60_000,
    retry: 1,
  });

  const schemaQ = useQuery({
    queryKey: ["metadata", "schema-version"],
    queryFn: () => datasetClient.fetch<z.infer<typeof SchemaVersion>>("schema-version", {}, SchemaVersion),
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

      {/* Dataset six states (hairline section, not a card) */}
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
                  const status = info.status;
                  // #89/#101: the published reason is a {code, detail} pair from a closed
                  // vocabulary. The code is translated; detail is operator-facing English
                  // (redacted at the boundary, #92) and shown VERBATIM on a secondary
                  // monospace line — a tooltip-only detail is an invisible reason.
                  const reasonCode = info.reason?.code;
                  const reasonDetail = info.reason?.detail;
                  return (
                    <tr key={key} className="border-b border-border/50 last:border-0">
                      <td className="py-1.5 pr-2">{t(`datasets.${key}`, { defaultValue: key })}</td>
                      <td className="py-1.5 pr-2">
                        <StatusBadge status={status} />
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums text-muted-foreground">
                        {info.updated_at ? formatDateTime(info.updated_at, locale) : t("common:data.na")}
                      </td>
                      <td className="py-1.5 text-muted-foreground">
                        <div>
                          {reasonCode
                            ? t(`freshness.reasonCodes.${reasonCode}`, { defaultValue: reasonCode })
                            : t("common:data.na")}
                        </div>
                        {reasonDetail ? (
                          <div className="max-w-[340px] truncate font-mono text-[10px] text-muted-foreground/80" title={reasonDetail}>
                            {reasonDetail}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title={t("freshness.none")} data-testid="status-freshness-empty" />
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
                  <th className="py-1.5 font-medium">{t("providers.status")}</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(sourcesQ.data.domains).map(([domain, raw]) => {
                  const info = raw as DomainEntry;
                  const usedFallback = Boolean(info.used_fallback);
                  const fromCache = Boolean(info.from_cache);
                  const provider = info.provider;
                  // #65: show the resolved provider and how it was served (fallback/cache)
                  // instead of bare Yes/No booleans.
                  const served = provider ?? t("common:data.na");
                  const annotation = fromCache
                    ? ` · ${t("providers.cache")}`
                    : usedFallback
                      ? ` · ${t("providers.fallback")}`
                      : "";
                  const reasonCode = info.reason?.code;
                  const reasonDetail = info.reason?.detail;
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
                        {/* #95: a degraded provider states a specific cause, not the bare
                            word "Degraded" — same reason rendering as the freshness table,
                            from the ONE redacted detail channel (#92). */}
                        <StatusBadge status={info.status} />
                        <div className="mt-0.5 text-muted-foreground">
                          {reasonCode
                            ? t(`freshness.reasonCodes.${reasonCode}`, { defaultValue: reasonCode })
                            : t("common:data.na")}
                          {reasonDetail ? (
                            <div
                              className="max-w-[340px] truncate font-mono text-[10px] text-muted-foreground/80"
                              title={reasonDetail}
                            >
                              {reasonDetail}
                            </div>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title={t("providers.none")} data-testid="status-providers-empty" />
        )}
      </section>
    </div>
  );
}
