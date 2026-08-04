import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTheme, type ThemePreference } from "@/hooks/useTheme";
import { cn } from "@/lib/utils";

/**
 * ThemeToggle: three-way theme preference control (ADR-0001).
 * dark | light | system — dark is the default for first-time visitors;
 * "system" is opt-in and the only mode that follows the OS appearance.
 */
const OPTIONS: { value: ThemePreference; icon: typeof Moon; key: string }[] = [
  { value: "dark", icon: Moon, key: "theme.dark" },
  { value: "light", icon: Sun, key: "theme.light" },
  { value: "system", icon: Monitor, key: "theme.system" },
];

export function ThemeToggle() {
  const { t } = useTranslation("common");
  const { preference, setPreference } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label={t("theme.label")}
      className="inline-flex items-center rounded-sm border border-hairline bg-surface-1"
      data-testid="theme-toggle"
    >
      {OPTIONS.map(({ value, icon: Icon, key }) => {
        const active = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            title={t(key)}
            onClick={() => setPreference(value)}
            className={cn(
              "inline-flex min-h-10 items-center gap-1 px-1.5 text-xs transition-colors duration-150 sm:h-7 sm:min-h-0 sm:px-2",
              active
                ? "bg-surface-2 text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
            data-testid={`theme-option-${value}`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            <span className="hidden sm:inline">{t(key)}</span>
          </button>
        );
      })}
    </div>
  );
}
