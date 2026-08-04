import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocale } from "@/hooks/useLocale";
import { Button } from "@/components/ui/Button";

/**
 * LanguageSwitch: language switch (does not navigate home; only replaces the URL language segment; persisted in localStorage).
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
      className="h-10 w-10 px-0 sm:h-8 sm:w-auto sm:px-3"
    >
      <Languages className="h-4 w-4" aria-hidden />
      <span className="hidden sm:inline">{next}</span>
    </Button>
  );
}
