import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocale } from "@/hooks/useLocale";
import { Button } from "@/components/ui/Button";

/**
 * LanguageSwitch：语言切换（不跳首页，仅替换 URL 语言段；localStorage 持久化）。
 */
export function LanguageSwitch() {
  const { t } = useTranslation("common");
  const { locale, toggleLocale } = useLocale();

  const next = locale === "en" ? t("lang.zh") : t("lang.en");

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={toggleLocale}
      aria-label={t("lang.switch")}
      data-testid="lang-switch"
      className="gap-1.5"
    >
      <Languages className="h-4 w-4" aria-hidden />
      <span>{next}</span>
    </Button>
  );
}
