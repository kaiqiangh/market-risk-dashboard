import { HashRouter } from "react-router-dom";
import { AppRoutes } from "./router";

/**
 * 应用外壳。
 * 使用 Hash Router（冻结，架构 §1.2）：GitHub Pages 刷新稳定性（#/zh/overview）。
 * 路由表与占位页面见 src/router.tsx；布局（Navbar/Footer/LanguageSwitch）在 T04 实现。
 */
export default function App() {
  return (
    <HashRouter>
      <AppRoutes />
    </HashRouter>
  );
}
