import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, beforeEach } from "vitest";
import { installFixtureFetch } from "./helpers/fetchMock";
import "@/i18n"; // side-effect: initialize i18n so t(themes.<key>) resolves labels
import ThemesPage from "@/pages/ThemesPage";

/**
 * ThemesPage coverage (#93 — the page previously had none): renders the expanded theme
 * cards with labels (i18n), change, percentile band and constituent chips from sectors.json.
 * i18n is the real module (like router.test.tsx); the fixture drives the data.
 */

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ThemesPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  installFixtureFetch();
});

describe("ThemesPage", () => {
  it("renders the 20-theme section with labels and constituent chips", async () => {
    renderPage();
    // Both fixture themes render with their i18n labels (locale detected as zh-CN here).
    expect(await screen.findByText("存储")).toBeInTheDocument();
    expect(screen.getByText("网络安全")).toBeInTheDocument();
    // Constituent chips are rendered from the payload.
    expect(screen.getByText("MU")).toBeInTheDocument();
    expect(screen.getByText("PANW")).toBeInTheDocument();
  });

  it("renders a percentile band for a computed percentile and warming-up for a short series", async () => {
    renderPage();
    await screen.findByText("网络安全");
    // memory percentile 90 → "Very High" band (zh: 极高).
    expect(screen.getByText("极高")).toBeInTheDocument();
    // cybersecurity percentile null with obs 30 → "warming up 30/100" (zh: 累积中 30/100).
    expect(screen.getByText("累积中 30 个观测")).toBeInTheDocument();
  });
});
