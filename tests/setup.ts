import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";
import i18n from "@/i18n";

/**
 * 全局测试设置：
 * - jest-dom 匹配器
 * - 每个用例前重置 i18n 语言为 zh-CN 与 localStorage（i18n 为模块单例，避免跨文件泄漏）
 */
beforeEach(async () => {
  window.localStorage.clear();
  await i18n.changeLanguage("zh-CN");
});
