import { useTranslation } from "react-i18next";
import { TrendingUp, TrendingDown, Minus, Database } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import { Badge } from "@/components/ui/Badge";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { RISK_DIMENSION_KEYS, RISK_EVIDENCE_KEYS, RISK_INDICATOR_KEYS, RISK_TREND_KEYS } from "@/lib/riskLabels";
import { riskLevelTone, toneClasses } from "@/lib/riskColors";
import { formatNumber, formatPercentile, formatRatio } from "@/lib/format";
import type { RiskDimension, RiskModelResult } from "@/schemas";

/**
 * RiskDimensionBreakdown: 6-dimension risk model breakdown (RiskLab core).
 * Dimension cards: score / configured weight / effective weight / coverage / trend / indicator details.
 */
export interface RiskDimensionBreakdownProps {
  result: RiskModelResult;
}

function DimensionTrendIcon({ trend }: { trend: RiskDimension["trend"] }) {
  if (trend === "rising") return <TrendingUp className="h-3.5 w-3.5" aria-hidden />;
  if (trend === "falling") return <TrendingDown className="h-3.5 w-3.5" aria-hidden />;
  return <Minus className="h-3.5 w-3.5" aria-hidden />;
}

export function RiskDimensionBreakdown({ result }: RiskDimensionBreakdownProps) {
  const { t, i18n } = useTranslation("risk");
  const locale = i18n.language;
  const totalTone = riskLevelTone(result.risk_level);
  const totalClasses = toneClasses(totalTone);
  const evidenceState = result.evidence_state ?? "insufficient_evidence";
  const evidenceCoverage = result.evidence_coverage ?? result.confidence_factors.coverage ?? 0;
  const scoreLowerBound = result.score_lower_bound ?? result.total_score;
  const scoreUpperBound = result.score_upper_bound ?? result.total_score;
  const evidenceVariant = evidenceState === "complete" ? "low" : evidenceState === "partial" ? "caution" : "na";

  return (
    <div className="flex flex-col gap-4">
      {/* Total score + confidence factors */}
      <Card>
        <CardHeader>
          <CardTitle>{t("score.breakdown")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <div className="rounded-md bg-muted/50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("score.title")}</p>
            <p className={`text-3xl font-bold tabular-nums ${totalClasses.text}`}>{formatNumber(result.total_score, locale)}</p>
          </div>
          <div className="rounded-md bg-muted/50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("score.confidence")}</p>
            <p className="text-2xl font-semibold tabular-nums">{formatRatio(result.confidence, locale)}</p>
            <Progress value={result.confidence * 100} barClassName={totalClasses.bg} className="mt-1" />
          </div>
          <div className="rounded-md bg-muted/50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("score.modelVersion")}</p>
            <p className="text-lg font-semibold tabular-nums">{result.model_version}</p>
          </div>
          <div className="rounded-md bg-muted/50 p-3" data-testid="risk-calibration-policy">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("calibration.title")}</p>
            <Badge variant={result.calibration_status === "calibrated" ? "low" : "caution"}>
              {t(`calibration.${result.calibration_status ?? "provisional"}`)}
            </Badge>
            <p className="mt-2 text-xs text-muted-foreground">
              {t("calibration.version")}: <span className="tabular-nums text-foreground">{result.calibration_policy_version ?? "1.0.0"}</span>
            </p>
          </div>
          <div className="rounded-md bg-muted/50 p-3">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("confidenceFactors.title")}</p>
            <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
              {Object.entries(result.confidence_factors).map(([k, v]) => (
                <li key={k} className="flex justify-between gap-2">
                  <span>{t(`confidenceFactors.${k}`, { defaultValue: t("confidenceFactors.unknown") })}</span>
                  <span className="tabular-nums text-foreground">{formatRatio(v, locale)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-md bg-muted/50 p-3" data-testid="risk-evidence-state">
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t("evidence.title")}</p>
            <Badge variant={evidenceVariant}>{t(RISK_EVIDENCE_KEYS[evidenceState])}</Badge>
            <p className="mt-2 text-xs text-muted-foreground">
              {t("evidence.coverage")}: <span className="tabular-nums text-foreground">{formatRatio(evidenceCoverage, locale)}</span>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("evidence.scoreRange")}: <span className="tabular-nums text-foreground">{formatNumber(scoreLowerBound, locale)}–{formatNumber(scoreUpperBound, locale)}</span>
            </p>
          </div>
        </CardContent>
        {result.disclaimer ? (
          <CardContent>
            <p className="text-[11px] leading-relaxed text-muted-foreground">{t("score.disclaimer")}</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{t("evidence.explanation")}</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{t("calibration.explanation")}</p>
          </CardContent>
        ) : null}
      </Card>

      {/* 6 dimension cards */}
      <div className="grid gap-4 lg:grid-cols-2">
        {result.dimensions.map((dim) => {
          const tone = riskLevelTone(
            dim.score >= 70 ? "high_risk" : dim.score >= 50 ? "caution" : dim.score >= 30 ? "low_risk" : "risk_on",
          );
          const classes = toneClasses(tone);
          const trendTone = dim.trend === "rising" ? "high" : dim.trend === "falling" ? "low" : "na";
          const trendClasses = toneClasses(trendTone);
          const dimensionEvidenceState = dim.evidence_state ?? (dim.coverage > 0 ? "partial" : "insufficient_evidence");
          return (
            <Card key={dim.key} data-testid="risk-dimension">
              <CardHeader className="flex-row items-start justify-between gap-2">
                <div className="flex flex-col gap-1">
                  <CardTitle>{t(RISK_DIMENSION_KEYS[dim.key])}</CardTitle>
                  <p className="text-[11px] text-muted-foreground">{t(RISK_DIMENSION_KEYS[dim.key])}</p>
                </div>
                <div className="flex flex-col items-end gap-1.5">
                  <div className={`flex items-center gap-1.5 text-sm font-medium ${trendClasses.text}`}>
                    <DimensionTrendIcon trend={dim.trend} />
                    <span>{t(RISK_TREND_KEYS[dim.trend])}</span>
                  </div>
                  <Badge variant={dimensionEvidenceState === "complete" ? "low" : dimensionEvidenceState === "partial" ? "caution" : "na"}>
                    {t(RISK_EVIDENCE_KEYS[dimensionEvidenceState])}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-2xl font-bold tabular-nums ${classes.text}`}>{formatNumber(dim.score, locale)}</span>
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{t("dimension.weight")}: {formatNumber(dim.weight, locale, 1)}%</span>
                    <span>{t("dimension.effectiveWeight")}: {formatNumber(dim.effective_weight, locale, 1)}%</span>
                    <span>{t("dimension.coverage")}: {formatRatio(dim.coverage, locale)}</span>
                  </div>
                </div>
                {dim.missing_indicators?.length ? (
                  <p className="text-xs text-muted-foreground">
                    {t("evidence.missingIndicators")}: {dim.missing_indicators.length}
                  </p>
                ) : null}
                <Progress value={dim.score} barClassName={classes.bg} />

                {/* Indicator details (desktop table / collapsible mobile cards) */}
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[480px] text-left text-xs">
                    <thead>
                      <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                        <th className="py-1.5 pr-2 font-medium">{t("indicator.label")}</th>
                        <th className="py-1.5 pr-2 text-right font-medium">{t("indicator.value")}</th>
                        <th className="py-1.5 pr-2 text-right font-medium">{t("indicator.percentile")}</th>
                        <th className="py-1.5 pr-2 text-right font-medium">{t("indicator.riskScore")}</th>
                        <th className="py-1.5 text-right font-medium">{t("indicator.status")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dim.indicators.map((ind) => (
                        <tr key={ind.key} className="border-b border-border/50 last:border-0" data-testid="risk-indicator">
                          <td className="py-1.5 pr-2">
                            <div className="flex items-center gap-1.5">
                              <span className="text-foreground">{t(RISK_INDICATOR_KEYS[ind.key] ?? "indicatorNames.unknown")}</span>
                              {ind.is_proxy ? (
                                <Badge variant="outline" className="px-1 py-0 text-[9px]">
                                  {t("indicator.proxy")}
                                </Badge>
                              ) : null}
                            </div>
                          </td>
                          <td className="py-1.5 pr-2 text-right tabular-nums">
                            {ind.value === null ? t("common:data.na") : formatNumber(ind.value, locale)}
                          </td>
                          <td className="py-1.5 pr-2 text-right tabular-nums">
                            {ind.percentile === null ? t("common:data.na") : formatPercentile(ind.percentile, locale)}
                          </td>
                          <td className="py-1.5 pr-2 text-right tabular-nums">
                            <span className={toneClasses(riskLevelTone(ind.risk_score >= 70 ? "high_risk" : ind.risk_score >= 50 ? "caution" : "low_risk")).text}>
                              {formatNumber(ind.risk_score, locale)}
                            </span>
                          </td>
                          <td className="py-1.5 text-right">
                            <StatusBadge status={ind.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Database className="h-3.5 w-3.5" aria-hidden />
        {t("dimension.disclaimer")}
      </p>
    </div>
  );
}
