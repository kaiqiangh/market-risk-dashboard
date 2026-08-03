import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { AssetHeatmap, type HeatmapCell } from "@/charts/AssetHeatmap";

/**
 * AssetHeatmapView: cross-asset heatmap view container (PRD §22.3 Cross-Asset Heatmap).
 * Desktop ECharts heatmap; on mobile the chart component automatically degrades to grid cards.
 */
export interface AssetHeatmapViewProps {
  cells: HeatmapCell[];
}

export function AssetHeatmapView({ cells }: AssetHeatmapViewProps) {
  const { t } = useTranslation("dashboard");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("heatmap.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <AssetHeatmap cells={cells} />
      </CardContent>
    </Card>
  );
}
