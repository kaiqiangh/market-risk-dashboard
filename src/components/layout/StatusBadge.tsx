import { useTranslation } from "react-i18next";
import { badgeFor } from "@/lib/freshness";
import { freshTone, type FreshTone } from "@/lib/riskColors";
import { Badge } from "@/components/ui/Badge";
import type { FreshnessStatus } from "@/schemas";

/**
 * StatusBadge: freshness six-state badge (architecture §8.5, ADR-0002).
 * Five states → icon + text + muted treatment; "fresh" uses no saturated color
 * (expected state), only stale/missing earn a warm tone. Color is never the only expression.
 * #66: a cache-replayed dataset renders a distinct badge (fromCache) instead of sharing
 * the delayed/degraded look.
 */
export interface StatusBadgeProps {
  status: FreshnessStatus;
  /** Whether to show the descriptive text (label only by default). */
  withDescription?: boolean;
  /** Cache replay (#66): served from the last-good cache, not fetched live. */
  fromCache?: boolean;
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

export function StatusBadge({ status, withDescription = false, fromCache = false, className }: StatusBadgeProps) {
  const { t } = useTranslation("common");
  const badge = badgeFor(status, fromCache);
  const tone = freshTone(status);
  const testId = fromCache ? "status-badge-cache" : `status-badge-${status}`;

  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`} title={t(badge.descriptionKey)}>
      <Badge variant={TONE_TO_VARIANT[tone]} data-testid={testId}>
        <span className={`h-1.5 w-1.5 rounded-full ${TONE_TO_DOT[tone]}`} aria-hidden />
        {t(badge.labelKey)}
      </Badge>
      {withDescription ? <span className="text-xs text-muted-foreground">{t(badge.descriptionKey)}</span> : null}
    </span>
  );
}
