import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { formatNumber } from "@/lib/format";
import type { EvidenceRef } from "@/schemas";

/**
 * EvidenceLink: evidence link (architecture §8.9 Evidence Linking).
 * Each conclusion carries evidence_refs; on click:
 * 1) if an element matching data-evidence-path exists on the page → scroll to and highlight that indicator card;
 * 2) always expand inline details (dataset / metric / value) to ensure accessibility (not dependent on scrolling).
 */
export interface EvidenceLinkProps {
  refs: EvidenceRef[];
}

export function EvidenceLink({ refs }: EvidenceLinkProps) {
  const { t, i18n } = useTranslation("common");
  const locale = i18n.language;
  const [active, setActive] = useState<string | null>(null);

  if (refs.length === 0) return null;

  const highlight = (ref: EvidenceRef): void => {
    const key = `${ref.dataset}:${ref.path}`;
    setActive((prev) => (prev === key ? null : key));
    const el = document.querySelector<HTMLElement>(`[data-evidence-path="${ref.path}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("ring-2", "ring-primary");
      window.setTimeout(() => el.classList.remove("ring-2", "ring-primary"), 2000);
    }
  };

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5" data-testid="evidence-link">
      <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
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
            className="cursor-pointer px-1.5 py-0 text-[10px] hover:bg-accent"
            onClick={() => highlight(ref)}
            title={`${ref.dataset} ${ref.path}`}
          >
            {ref.metric}
            {expanded ? (
              <span className="ml-1 font-mono text-muted-foreground">
                {typeof ref.value === "number" ? formatNumber(ref.value, locale) : ref.value}
              </span>
            ) : null}
          </Badge>
        );
      })}
    </div>
  );
}
