import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Progress：风险分/置信度条（语义色 + 文本）。
 */
export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value: number; // 0-100
  barClassName?: string;
  /** 进度条高度（默认 h-2）。 */
  barHeightClass?: string;
}

export function Progress({ value, className, barClassName, barHeightClass = "h-2", ...props }: ProgressProps) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cn("w-full overflow-hidden rounded-full bg-muted", barHeightClass, className)}
      {...props}
    >
      <div
        className={cn("h-full rounded-full transition-all", barClassName)}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
