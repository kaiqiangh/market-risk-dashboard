import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { formatNumber } from "@/lib/format";
import type { EvidenceRef } from "@/schemas";

/**
 * EvidenceLink：证据链接（架构 §8.9 Evidence Linking）。
 * 每个结论携带 evidence_refs；点击后：
 * 1) 若页面存在 data-evidence-path 匹配的元素 → 滚动并高亮该指标卡片；
 * 2) 始终展开内联详情（dataset / metric / value），保证可访问性（不依赖滚动）。
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
