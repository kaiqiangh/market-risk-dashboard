import { HashRouter } from "react-router-dom";
import { AppRoutes } from "./router";

/**
 * App shell.
 * Uses Hash Router (frozen, architecture §1.2) for GitHub Pages refresh stability (#/zh/overview).
 * See src/router.tsx for the route table and placeholder pages; layout (Navbar/Footer/LanguageSwitch) is implemented in T04.
 */
export default function App() {
  return (
    <HashRouter>
      <AppRoutes />
    </HashRouter>
  );
}
