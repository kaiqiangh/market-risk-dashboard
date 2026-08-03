import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Skeleton：加载占位（避免大面积闪烁）。
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}
