import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { formatDate, formatNumber } from "@/lib/format";
import type { EvidenceRef } from "@/schemas";

/**
 * EvidenceLink: evidence citation chips (architecture §8.9, spec #23 ticket #29).
 * Each chip shows dataset:metric + updated timestamp (source + timestamp), wired to
 * the underlying fact/news item. Click expands the inline value (accessibility — not
 * dependent on scrolling).
 */
export interface EvidenceLinkProps {
  refs: EvidenceRef[];
}

export function EvidenceLink({ refs }: EvidenceLinkProps) {
  const { t, i18n } = useTranslation("common");
  const locale = i18n.language;
  const [active, setActive] = useState<string | null>(null);

  if (refs.length === 0) return null;

  const toggleActive = (ref: EvidenceRef): void => {
    const key = `${ref.dataset}:${ref.path}`;
    setActive((prev) => (prev === key ? null : key));
  };

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5" data-testid="evidence-link">
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Link2 className="h-3 w-3" aria-hidden />
        {t("evidence.label")}
      </span>
      {refs.slice(0, 3).map((ref) => {
        const key = `${ref.dataset}:${ref.path}`;
        const expanded = active === key;
        return (
          <Badge
            key={key}
            variant="outline"
            className="cursor-pointer rounded-sm border-hairline bg-surface-2 px-1.5 py-0 font-mono text-xs text-muted-foreground transition-colors duration-150 hover:border-primary/40 hover:text-foreground"
            role="button"
            tabIndex={0}
            aria-pressed={expanded}
            onClick={() => toggleActive(ref)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                toggleActive(ref);
              }
            }}
            title={`${ref.dataset} ${ref.path}`}
          >
            {ref.dataset}:{ref.metric}
            {ref.updated_at ? (
              <span className="text-muted-foreground">· {formatDate(ref.updated_at, locale)}</span>
            ) : null}
            {expanded ? (
              <span className="ml-1 text-foreground">
                {typeof ref.value === "number" ? formatNumber(ref.value, locale) : ref.value}
              </span>
            ) : null}
          </Badge>
        );
      })}
    </div>
  );
}
