import { useTranslation } from "react-i18next";
import { NewsCard } from "./NewsCard";
import { EmptyState } from "@/components/ui/EmptyState";
import type { NewsItem } from "@/schemas";

/**
 * NewsList: news list (sorted by importance; single column on mobile, 2 columns on desktop).
 */
export interface NewsListProps {
  items: NewsItem[];
  limit?: number;
}

export function NewsList({ items, limit }: NewsListProps) {
  const { t } = useTranslation("news");
  const sorted = [...items].sort((a, b) => b.importance - a.importance);
  const shown = limit ? sorted.slice(0, limit) : sorted;

  if (shown.length === 0) {
    return <EmptyState title={t("none")} data-testid="news-empty" />;
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="news-list">
      {shown.map((item) => (
        <NewsCard key={item.id} item={item} />
      ))}
    </div>
  );
}
