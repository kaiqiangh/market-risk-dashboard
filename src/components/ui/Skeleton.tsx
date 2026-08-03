import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Skeleton: loading placeholder (avoids large-area flicker).
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-lg bg-muted", className)} {...props} />;
}
