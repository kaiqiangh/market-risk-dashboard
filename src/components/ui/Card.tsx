import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Card (terminal style, CONTEXT.md card policy): surface-1 + 1px hairline,
 * 4px radius, NO shadow at rest (glow budget). Cards are earned, not default:
 * KPI readouts and independently-fresh widgets only; everything else should be
 * a hairline-divided section on surface-0.
 */

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-lg border border-hairline bg-card text-card-foreground", className)}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 p-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-sm font-semibold leading-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-xs text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-3 pt-0", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center p-3 pt-0", className)} {...props} />;
}
