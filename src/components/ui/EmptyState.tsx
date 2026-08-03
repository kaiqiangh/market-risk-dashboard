import * as React from "react";
import { Inbox } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";

/**
 * EmptyState：数据缺失空态（架构 §8.8 缺失渲染 EmptyState）。
 */
export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  message?: string;
}

export function EmptyState({ title, message, className, ...props }: EmptyStateProps) {
  const { t } = useTranslation("common");
  return (
    <div
      className={cn(
        "flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-6 text-center",
        className,
      )}
      {...props}
    >
      <Inbox className="h-8 w-8 text-risk-na" aria-hidden />
      <p className="text-sm font-medium text-foreground">{title ?? t("empty.title")}</p>
      {message ? <p className="max-w-md text-xs text-muted-foreground">{message}</p> : null}
    </div>
  );
}
