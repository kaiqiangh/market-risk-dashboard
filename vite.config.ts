import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vitejs.dev/config/
export default defineConfig({
  // GitHub Pages 项目站点部署路径（冻结，架构 §1.2）
  base: "/market-risk-dashboard/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // dev 阶段仅用于本地调试；生产数据一律走 public/data 静态文件
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        /**
         * 手动分包（架构 §1.2/§23：按页面和模块懒加载 + ECharts 按需）。
         * - echarts：ECharts 按需模块（core/charts/components/renderers）+ zrender，独立缓存
         * - react-vendor / query / i18n / ui：框架级依赖，长期缓存
         * - 页面组件仍由 React.lazy 拆分（src/router.tsx），随路由按需加载
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
