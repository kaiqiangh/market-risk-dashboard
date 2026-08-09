import * as React from "react";
import { cn } from "@/lib/utils";
import { Card } from "./Card";

/**
 * KpiCard: the primary sanctioned card of the card policy (CONTEXT.md) —
 * a small KPI readout: muted 11px label, tabular-numeral value, muted footer.
 */
export interface KpiCardProps extends React.HTMLAttributes<HTMLDivElement> {
  label: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function KpiCard({ label, children, footer, className, ...props }: KpiCardProps) {
  return (
    <Card className={cn("p-3", className)} {...props}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-baseline gap-2">{children}</div>
      {footer ? <div className="mt-1 text-xs text-muted-foreground">{footer}</div> : null}
    </Card>
  );
}
