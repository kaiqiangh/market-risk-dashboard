import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Badge (shadcn/ui style). tone maps to risk semantic colors (architecture §8.6: color is not the only expression).
 */

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-muted text-muted-foreground",
        outline: "border-border text-foreground",
        low: "border-risk-low/40 bg-risk-low/10 text-risk-low",
        caution: "border-risk-caution/40 bg-risk-caution/10 text-risk-caution",
        high: "border-risk-high/40 bg-risk-high/10 text-risk-high",
        severe: "border-risk-severe/40 bg-risk-severe/10 text-risk-severe",
        na: "border-risk-na/40 bg-risk-na/10 text-risk-na",
        // Freshness family (ADR-0002): ok is muted by design; only warn/bad earn a warm tone
        freshOk: "border-hairline bg-muted/40 text-muted-foreground",
        freshWarn: "border-fresh-warn/40 bg-fresh-warn/10 text-fresh-warn",
        freshBad: "border-fresh-bad/40 bg-fresh-bad/10 text-fresh-bad",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
