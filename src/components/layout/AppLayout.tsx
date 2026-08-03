import { Suspense } from "react";
import { Outlet } from "react-router-dom";
import { Navbar } from "./Navbar";
import { Footer } from "./Footer";
import { LocaleSync } from "@/hooks/useLocale";
import { Skeleton } from "@/components/ui/Skeleton";

/**
 * AppLayout: global layout shell (architecture §1.2/§4.3).
 * - LocaleSync: syncs the URL language segment → i18n (language kept across refresh / back-forward).
 * - Suspense: route lazy-loading fallback (on-demand ECharts + code splitting).
 */
export function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <LocaleSync />
      <Navbar />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Suspense
          fallback={
            <div className="flex flex-col gap-4" data-testid="page-loading">
              <Skeleton className="h-8 w-48" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-64 w-full" />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
