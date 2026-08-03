import { useTranslation } from "react-i18next";

/**
 * Footer：免责声明 + 数据时间。
 */
export function Footer() {
  const { t } = useTranslation("common");
  return (
    <footer className="border-t border-border py-4">
      <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 text-center text-xs text-muted-foreground">
        <p>{t("footer.disclaimer")}</p>
        <p>{t("footer.calibration")}</p>
      </div>
    </footer>
  );
}
