import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";
import i18n from "@/i18n";

/**
 * Global test setup:
 * - jest-dom matchers
 * - reset i18n language to zh-CN and clear localStorage before each case
 *   (i18n is a module singleton; avoids cross-file leakage)
 */
beforeEach(async () => {
  window.localStorage.clear();
  await i18n.changeLanguage("zh-CN");
});
