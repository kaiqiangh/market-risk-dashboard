import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";

/**
 * ImportanceBadge: news/event importance (high score highlighted, color + text).
 */
export interface ImportanceBadgeProps {
  importance: number; // 0-100
  highThreshold?: number;
  mediumThreshold?: number;
}

export function ImportanceBadge({ importance, highThreshold = 70, mediumThreshold = 40 }: ImportanceBadgeProps) {
  const { t } = useTranslation("news");
  if (importance >= highThreshold) {
    return (
      <Badge variant="high" data-testid="importance-high">
        {t("importance.high")}
      </Badge>
    );
  }
  if (importance >= mediumThreshold) {
    return (
      <Badge variant="caution" data-testid="importance-medium">
        {t("importance.medium")}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" data-testid="importance-low">
      {t("importance.low")}
    </Badge>
  );
}
