import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Progress: risk score / confidence bar (semantic color + text).
 */
export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value: number; // 0-100
  barClassName?: string;
  /** Progress bar height (default h-2). */
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
