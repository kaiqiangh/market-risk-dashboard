import { useTranslation } from "react-i18next";
import { badgeFor } from "@/lib/freshness";
import { freshnessTone } from "@/lib/riskColors";
import { Badge } from "@/components/ui/Badge";
import type { FreshnessStatus } from "@/schemas";

/**
 * StatusBadge: freshness five-state badge (architecture §8.5).
 * Five states → icon + text + color (color is not the only expression).
 */
export interface StatusBadgeProps {
  status: FreshnessStatus;
  /** Whether to show the descriptive text (label only by default). */
  withDescription?: boolean;
  className?: string;
}

const TONE_TO_BADGE: Record<string, "low" | "caution" | "high" | "severe" | "na"> = {
  low: "low",
  caution: "caution",
  high: "high",
  severe: "severe",
  na: "na",
};

export function StatusBadge({ status, withDescription = false, className }: StatusBadgeProps) {
  const { t } = useTranslation("common");
  const badge = badgeFor(status);
  const tone = freshnessTone(status);
  const variant = TONE_TO_BADGE[tone];

  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`} title={t(badge.descriptionKey)}>
      <Badge variant={variant} data-testid={`status-badge-${status}`}>
        <span
          className={`h-1.5 w-1.5 rounded-full ${tone === "low" ? "bg-risk-low" : tone === "caution" ? "bg-risk-caution" : tone === "high" ? "bg-risk-high" : tone === "severe" ? "bg-risk-severe" : "bg-risk-na"}`}
          aria-hidden
        />
        {t(badge.labelKey)}
      </Badge>
      {withDescription ? <span className="text-xs text-muted-foreground">{t(badge.descriptionKey)}</span> : null}
    </span>
  );
}
