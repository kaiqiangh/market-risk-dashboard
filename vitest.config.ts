import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Standalone Vitest config (vitest reads this file first).
 * Decouples the test config from vite.config.ts so test-related fields do not leak into the build config.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary"],
      reportsDirectory: "./coverage",
    },
  },
});
