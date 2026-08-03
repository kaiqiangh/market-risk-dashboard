import path from "node:path";
import { defineConfig } from "vitest/config";

/**
 * Vitest 独立配置（vitest 优先读取本文件）。
 * 测试配置与 vite.config.ts 解耦，避免把测试相关字段混入构建配置。
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: false,
  },
});
