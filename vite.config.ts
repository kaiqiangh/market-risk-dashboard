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
  },
});
