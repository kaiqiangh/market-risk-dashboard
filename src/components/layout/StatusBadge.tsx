import { useTranslation } from "react-i18next";
import { badgeFor } from "@/lib/freshness";
import { freshTone, type FreshTone } from "@/lib/riskColors";
import { Badge } from "@/components/ui/Badge";
import type { FreshnessStatus } from "@/schemas";

/**
 * StatusBadge: freshness five-state badge (architecture §8.5, ADR-0002).
 * Five states → icon + text + muted treatment; "fresh" uses no saturated color
 * (expected state), only stale/missing earn a warm tone. Color is never the only expression.
 */
export interface StatusBadgeProps {
  status: FreshnessStatus;
  /** Whether to show the descriptive text (label only by default). */
  withDescription?: boolean;
  className?: string;
}

const TONE_TO_VARIANT: Record<FreshTone, "freshOk" | "freshWarn" | "freshBad"> = {
  ok: "freshOk",
  warn: "freshWarn",
  bad: "freshBad",
  na: "freshOk",
};

const TONE_TO_DOT: Record<FreshTone, string> = {
  ok: "bg-fresh-ok",
  warn: "bg-fresh-warn",
  bad: "bg-fresh-bad",
  na: "bg-muted-foreground",
};

export function StatusBadge({ status, withDescription = false, className }: StatusBadgeProps) {
  const { t } = useTranslation("common");
  const badge = badgeFor(status);
  const tone = freshTone(status);

  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`} title={t(badge.descriptionKey)}>
      <Badge variant={TONE_TO_VARIANT[tone]} data-testid={`status-badge-${status}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${TONE_TO_DOT[tone]}`} aria-hidden />
        {t(badge.labelKey)}
      </Badge>
      {withDescription ? <span className="text-xs text-muted-foreground">{t(badge.descriptionKey)}</span> : null}
    </span>
  );
}
