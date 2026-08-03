import { AlertTriangle, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "./Button";
import { cn } from "@/lib/utils";

/**
 * ErrorState：fetch/Zod 失败渲染（架构 §8.8：永不静默吞错，带错误详情 + 重试）。
 */
export interface ErrorStateProps {
  title?: string;
  message?: string;
  /** 详细错误（如 SchemaError.issues）。 */
  detail?: string[];
  onRetry?: () => void | Promise<unknown>;
  className?: string;
}

export function ErrorState({ title, message, detail, onRetry, className }: ErrorStateProps) {
  const { t } = useTranslation("common");
  return (
    <div
      role="alert"
      className={cn(
        "flex min-h-[160px] flex-col items-center justify-center gap-2 rounded-lg border border-risk-severe/40 bg-risk-severe/5 p-6 text-center",
        className,
      )}
    >
      <AlertTriangle className="h-8 w-8 text-risk-severe" aria-hidden />
      <p className="text-sm font-medium text-foreground">{title ?? t("error.title")}</p>
      <p className="max-w-md text-xs text-muted-foreground">{message ?? t("error.message")}</p>
      {detail && detail.length > 0 ? (
        <ul className="max-w-lg text-left text-[11px] text-muted-foreground">
          {detail.slice(0, 5).map((line, i) => (
            <li key={i} className="truncate font-mono">
              {line}
            </li>
          ))}
        </ul>
      ) : null}
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-1">
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          {t("error.retry")}
        </Button>
      ) : null}
    </div>
  );
}
