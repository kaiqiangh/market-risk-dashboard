import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  // GitHub Pages project site deployment path (frozen, architecture §1.2)
  base: "/market-risk-dashboard/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // Dev mode is only for local debugging; production data always comes from public/data static files
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        /**
         * Manual chunking (architecture §1.2/§23: lazy loading per page and module + on-demand ECharts).
         * - echarts: on-demand ECharts modules (core/charts/components/renderers) + zrender, cached independently
         * - react-vendor / query / i18n / ui: framework-level dependencies, long-term caching
         * - page components are still split by React.lazy (src/router.tsx), loaded on demand per route
         */
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/node_modules\/(echarts|zrender)\//.test(id)) return "echarts";
          if (/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)) {
            return "react-vendor";
          }
          if (/node_modules\/@tanstack\//.test(id)) return "query";
          if (/node_modules\/(i18next|react-i18next)\//.test(id)) return "i18n";
          if (/node_modules\/(lucide-react|class-variance-authority|clsx|tailwind-merge|@radix-ui)\//.test(id)) {
            return "ui";
          }
          return "vendor";
        },
      },
    },
  },
});
