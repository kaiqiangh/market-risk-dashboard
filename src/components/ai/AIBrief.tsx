import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import { Sparkles, ShieldAlert, TrendingUp, Scale } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Progress } from "@/components/ui/Progress";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { EvidenceLink } from "./EvidenceLink";
import { riskLevelKey, regimeKey } from "@/lib/riskLabels";
import { riskLevelTone, toneClasses, type RiskTone } from "@/lib/riskColors";
import { formatDateTime, formatRatio } from "@/lib/format";
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
 * AIBrief: AI market brief (renders analysis.{lang}.json, architecture §1.5/§3.4; spec #23 ticket #29).
 * - Visual quarantine: 2px accent left border + "AI" chip — generated content is never
 *   confusable with deterministic data.
 * - Evidence-driven: every claim carries inline citation chips (EvidenceLink) wired to
 *   facts/news sources; the header shows generation time + freshness treatment.
 * - Missing data / generation failure → honest degraded state, never fabricated content.
 */

export interface AIBriefProps {
  /** Analysis data (current language). */
  analysis?: AnalysisDataset;
  /** Loading. */
  loading?: boolean;
  /** Fetch failed (404 / network / validation failure). */
  error?: boolean;
}

/** Quarantined card chrome: 2px accent left border marks generated content. */
const QUARANTINE_CLASS = "border-l-2 border-l-primary";

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
          <li key={i} className="rounded-sm border border-hairline bg-surface-2/40 p-2">
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
  const toneText = toneClasses(tone).text;
  return (
    <div className="rounded-sm border border-hairline bg-surface-2/40 p-3">
      <p className={`text-xs font-semibold ${toneText}`}>{title}</p>
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
      <Card className={QUARANTINE_CLASS} data-testid="ai-brief-loading">
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
      <Card className={QUARANTINE_CLASS} data-testid="ai-brief-degraded">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-fresh-warn" aria-hidden />
            {t("aiBrief.title")}
            <span className="rounded-sm border border-primary/40 px-1 py-0 font-mono text-[10px] text-primary">AI</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2 rounded-sm border border-fresh-warn/40 bg-fresh-warn/5 p-4">
            <p className="text-sm font-medium text-foreground">{t("aiBrief.degraded")}</p>
            <p className="text-xs text-muted-foreground">{t("aiBrief.degradedHint")}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  // #66: honest empty state — when the inputs the brief was built from were degraded or
  // missing, the brief must say plainly it has no fresh basis rather than narrate numbers
  // it knows are not trustworthy.
  const hasFreshBasis = !["degraded", "missing"].includes(analysis.data_freshness);
  if (!hasFreshBasis) {
    return (
      <Card className={QUARANTINE_CLASS} data-testid="ai-brief-no-basis">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-fresh-warn" aria-hidden />
            {t("aiBrief.title")}
            <span className="rounded-sm border border-primary/40 px-1 py-0 font-mono text-[10px] text-primary">AI</span>
            <span className="ml-auto flex items-center gap-2 text-[11px] font-normal text-muted-foreground">
              <StatusBadge status={analysis.data_freshness} />
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2 rounded-sm border border-fresh-warn/40 bg-fresh-warn/5 p-4">
            <p className="text-sm font-medium text-foreground">{t("aiBrief.noFreshBasis")}</p>
            <p className="text-xs text-muted-foreground">{t("aiBrief.noFreshBasisHint")}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const stateTone = stateToneFromString(analysis.market_state);

  return (
    <Card className={QUARANTINE_CLASS} data-testid="ai-brief">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" aria-hidden />
          {t("aiBrief.title")}
          <span className="rounded-sm border border-primary/40 px-1 py-0 font-mono text-[10px] text-primary">AI</span>
          <span className="ml-auto flex items-center gap-2 text-[11px] font-normal text-muted-foreground">
            <StatusBadge status={analysis.data_freshness} />
            <span className="font-mono tabular-nums">{formatDateTime(analysis.generated_at, locale)}</span>
          </span>
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
        <EvidenceLink refs={analysis.evidence_refs} />
      </CardContent>
    </Card>
  );
}
