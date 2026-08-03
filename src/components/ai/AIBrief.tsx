import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import { Sparkles, ShieldAlert, TrendingUp, Scale } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";
import { EvidenceLink } from "./EvidenceLink";
import { riskLevelKey, regimeKey } from "@/lib/riskLabels";
import { riskLevelTone, toneClasses, type RiskTone } from "@/lib/riskColors";
import { formatRatio } from "@/lib/format";
import type { AnalysisDataset, SignalClaim } from "@/schemas";

/** market_state in the analysis file is a string; map loosely to a semantic color. */
function stateToneFromString(state: string): RiskTone {
  try {
    return riskLevelTone(state as Parameters<typeof riskLevelTone>[0]);
  } catch {
    return "caution";
  }
}

/**
 * AIBrief: AI market brief (renders analysis.{lang}.json, architecture §1.5/§3.4).
 * - Missing data / generation failure → show degraded rather than broken (degraded card).
 * - Each conclusion carries evidence_refs → highlighted via EvidenceLink.
 */

export interface AIBriefProps {
  /** Analysis data (current language). */
  analysis?: AnalysisDataset;
  /** Loading. */
  loading?: boolean;
  /** Fetch failed (404 / network / validation failure). */
  error?: boolean;
}

function SignalList({ title, icon, signals }: { title: string; icon: ReactNode; signals: SignalClaim[] }) {
  if (signals.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {icon}
        {title}
      </p>
      <ul className="flex flex-col gap-2">
        {signals.map((s, i) => (
          <li key={i} className="rounded-md border border-border bg-muted/30 p-2">
            <p className="text-xs leading-relaxed text-foreground">{s.claim}</p>
            <EvidenceLink refs={s.evidence_refs} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function CaseBlock({
  title,
  caseData,
  tone,
}: {
  title: string;
  caseData: { title: string; points: string[]; evidence_refs: AnalysisDataset["bull_case"]["evidence_refs"] };
  tone: "low" | "caution" | "high" | "severe" | "na";
}) {
  const classes = toneClasses(tone);
  return (
    <div className={`rounded-md border ${classes.border} ${classes.softBg} p-3`}>
      <p className={`text-xs font-semibold ${classes.text}`}>{title}</p>
      <p className="mt-1 text-xs font-medium text-foreground">{caseData.title}</p>
      <ul className="mt-1 flex list-inside list-disc flex-col gap-1 text-xs text-muted-foreground">
        {caseData.points.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
      <EvidenceLink refs={caseData.evidence_refs} />
    </div>
  );
}

export function AIBrief({ analysis, loading = false, error = false }: AIBriefProps) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;

  if (loading) {
    return (
      <Card data-testid="ai-brief-loading">
        <CardHeader>
          <CardTitle>{t("aiBrief.title")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-20 w-full" />
        </CardContent>
      </Card>
    );
  }

  if (error || !analysis) {
    return (
      <Card data-testid="ai-brief-degraded">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-risk-caution" aria-hidden />
            {t("aiBrief.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2 rounded-md border border-risk-caution/40 bg-risk-caution/5 p-4">
            <p className="text-sm font-medium text-foreground">{t("aiBrief.degraded")}</p>
            <p className="text-xs text-muted-foreground">{t("aiBrief.degradedHint")}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const stateTone = stateToneFromString(analysis.market_state);

  return (
    <Card data-testid="ai-brief">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden />
          {t("aiBrief.title")}
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={stateTone} className="w-fit">
            {t(`risk:${riskLevelKey(analysis.market_state)}`)}
          </Badge>
          <Badge variant="outline" className="w-fit">
            {t(`risk:${regimeKey(analysis.market_regime)}`)}
          </Badge>
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
            {t("aiBrief.confidence")}: <span className="font-semibold tabular-nums text-foreground">{formatRatio(analysis.confidence, locale)}</span>
          </span>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-sm leading-relaxed text-foreground">{analysis.summary}</p>

        {analysis.what_changed_today.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">{t("aiBrief.changedToday")}</p>
            <ul className="flex list-inside list-disc flex-col gap-0.5 text-xs text-foreground">
              {analysis.what_changed_today.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <SignalList title={t("aiBrief.topDrivers")} icon={<TrendingUp className="h-3.5 w-3.5 text-risk-high" aria-hidden />} signals={analysis.top_risk_drivers} />
        <SignalList title={t("aiBrief.supporting")} icon={<TrendingUp className="h-3.5 w-3.5 text-risk-low" aria-hidden />} signals={analysis.supporting_signals} />
        <SignalList title={t("aiBrief.contradicting")} icon={<Scale className="h-3.5 w-3.5 text-risk-caution" aria-hidden />} signals={analysis.contradicting_signals} />

        <div className="grid gap-3 md:grid-cols-3">
          <CaseBlock title={t("aiBrief.bullCase")} caseData={analysis.bull_case} tone="low" />
          <CaseBlock title={t("aiBrief.baseCase")} caseData={analysis.base_case} tone="caution" />
          <CaseBlock title={t("aiBrief.bearCase")} caseData={analysis.bear_case} tone="high" />
        </div>

        {analysis.watch_next.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-xs font-medium text-muted-foreground">{t("aiBrief.watchNext")}</p>
            <ul className="flex list-inside list-disc flex-col gap-0.5 text-xs text-foreground">
              {analysis.watch_next.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <Progress value={analysis.confidence * 100} barClassName="bg-primary" className="h-1.5" />
        <p className="text-[10px] text-muted-foreground">
          {t("aiBrief.generatedAt")}: {analysis.generated_at}
        </p>
      </CardContent>
    </Card>
  );
}
