import { HashRouter } from "react-router-dom";
import { AppRoutes } from "./router";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";

/**
 * App shell.
 * Uses Hash Router (frozen, architecture §1.2) for GitHub Pages refresh stability (#/zh/overview).
 * See src/router.tsx for the route table and placeholder pages; layout (Navbar/Footer/LanguageSwitch) is implemented in T04.
 */
export default function App() {
  return (
    <HashRouter>
      <ErrorBoundary>
        <AppRoutes />
      </ErrorBoundary>
    </HashRouter>
  );
}
