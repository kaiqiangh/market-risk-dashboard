import { useTranslation } from "react-i18next";
import { ExternalLink, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { ImportanceBadge } from "./ImportanceBadge";
import { formatRelativeTime } from "@/lib/format";
import { displayNewsSource, safeDisplayText } from "@/lib/displayLanguage";
import type { NewsItem } from "@/schemas";

/**
 * NewsCard: single news card (title / source / time / importance / sentiment / related assets).
 * Does not render untrusted HTML (architecture §8.13: AI output is rendered escaped, text only).
 */
export interface NewsCardProps {
  item: NewsItem;
}

function SentimentIcon({ sentiment }: { sentiment: NewsItem["sentiment"] }) {
  if (sentiment === "positive") return <TrendingUp className="h-3.5 w-3.5 text-risk-low" aria-hidden />;
  if (sentiment === "negative") return <TrendingDown className="h-3.5 w-3.5 text-risk-severe" aria-hidden />;
  return <Minus className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />;
}

export function NewsCard({ item }: NewsCardProps) {
  const { t, i18n } = useTranslation("news");
  const locale = i18n.language;
  const zh = locale.toLowerCase().startsWith("zh");
  // The active locale is the only source for human-readable prose. Missing translations
  // must be visible as a localized state rather than silently switching languages.
  const title = safeDisplayText(zh ? item.title_zh : item.title, locale, t("translationUnavailable"));
  const rawSummary = zh ? item.summary_zh : item.summary;
  const summary = rawSummary && safeDisplayText(rawSummary, locale, t("translationUnavailable"));

  return (
    <Card data-testid="news-card">
      <CardContent className="flex flex-col gap-1.5 p-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ImportanceBadge importance={item.importance} />
            <SentimentIcon sentiment={item.sentiment} />
            <span className="text-[11px] text-muted-foreground">{formatRelativeTime(item.published_at, locale)}</span>
          </div>
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
            aria-label={t("readMore")}
          >
            {t("readMore")}
            <ExternalLink className="h-3 w-3" aria-hidden />
          </a>
        </div>
        <p className="break-words text-sm font-medium leading-snug text-foreground">{title}</p>
        {summary ? <p className="break-words text-xs leading-relaxed text-muted-foreground">{summary}</p> : null}
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="rounded bg-muted px-1.5 py-0.5">{displayNewsSource(item.source, locale)}</span>
          {item.assets.length > 0 ? (
            <span className="flex items-center gap-1">
              {item.assets.slice(0, 4).map((a) => (
                <span key={a} className="rounded bg-muted px-1.5 py-0.5 font-mono">
                  {a}
                </span>
              ))}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
