import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTheme } from "@/hooks/useTheme";
import { Button } from "@/components/ui/Button";

/**
 * ThemeToggle: dark/light toggle (dark by default, persisted in localStorage).
 */
export function ThemeToggle() {
  const { t } = useTranslation("common");
  const { theme, toggleTheme, isDark } = useTheme();

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      aria-label={t("theme.toggle")}
      title={t("theme.toggle")}
      data-testid="theme-toggle"
    >
      {isDark ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
      <span className="sr-only">{theme === "dark" ? t("theme.light") : t("theme.dark")}</span>
    </Button>
  );
}
