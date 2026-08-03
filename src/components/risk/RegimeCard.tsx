import { useTranslation } from "react-i18next";
import { ShieldAlert } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { regimeTone, toneClasses } from "@/lib/riskColors";
import { REGIME_KEYS } from "@/lib/riskLabels";
import type { MarketRegime } from "@/schemas";

/**
 * RegimeCard：市场状态（Market Regime，9 状态规则引擎输出）。
 */
export interface RegimeCardProps {
  regime: MarketRegime;
  evidence?: string[];
}

export function RegimeCard({ regime, evidence = [] }: RegimeCardProps) {
  const { t } = useTranslation("risk");
  const tone = regimeTone(regime);
  const classes = toneClasses(tone);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-muted-foreground" aria-hidden />
          {t("regime.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Badge variant={tone} className={`w-fit text-sm ${classes.bg}`} data-testid="market-regime">
          {t(REGIME_KEYS[regime])}
        </Badge>
        {evidence.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {evidence.map((line, i) => (
              <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" aria-hidden />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">{t("regime.noEvidence")}</p>
        )}
      </CardContent>
    </Card>
  );
}
