import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { AssetHeatmap, type HeatmapCell } from "@/charts/AssetHeatmap";

/**
 * AssetHeatmapView：跨资产热力视图容器（PRD §22.3 Cross-Asset Heatmap）。
 * 桌面 ECharts 热力图；移动端由图表组件自动降级为网格卡片。
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
