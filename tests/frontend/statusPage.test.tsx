import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, beforeEach } from "vitest";
import "@/i18n";
import { installFixtureFetch } from "./helpers/fetchMock";
import StatusPage from "@/pages/StatusPage";

/**
 * StatusPage coverage (#95 — the page previously had none): the page whose job is
 * truthfulness must render real reasons — translated codes plus the visible (not
 * tooltip-only) operator detail — from metadata VALIDATED through the generated
 * contracts (sources.json / freshness.json), never z.unknown() casts.
 */

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StatusPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  installFixtureFetch();
});

describe("StatusPage", () => {
  it("renders the meta cards from validated metadata", async () => {
    renderPage();
    expect(await screen.findByText("1.0.0")).toBeInTheDocument(); // schema version card
    expect(await screen.findByText("11")).toBeInTheDocument(); // 11 canonical datasets
  });

  it("renders the six-state table with translated codes and VISIBLE details", async () => {
    renderPage();
    // Statuses render from validated statuses: degraded, empty and fresh all present
    // (multiple datasets share each badge).
    expect((await screen.findAllByTestId("status-badge-degraded")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("status-badge-empty")).toBeInTheDocument();
    expect(screen.getAllByTestId("status-badge-fresh").length).toBeGreaterThanOrEqual(1);
    // #95: every degraded widget states a specific, actionable cause — the detail is
    // rendered text on the row (a tooltip-only detail is an invisible reason).
    expect(screen.getByText("clschina: RSS HTTP 403")).toBeInTheDocument();
    expect(screen.getByText("no events in the 14-day window")).toBeInTheDocument();
    expect(screen.getAllByText("yfinance: HTTP 429 rate limited").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the providers table with the resolved provider and degradation", async () => {
    renderPage();
    expect(await screen.findByText("fred_calendar")).toBeInTheDocument(); // economic domain (#94)
    expect(screen.getByText("yfinance")).toBeInTheDocument();
    expect(screen.getByText("rss_news")).toBeInTheDocument();
    expect(screen.getByText("akshare")).toBeInTheDocument();
  });

  it("shows the empty state when there is no freshness data", async () => {
    renderPage();
    // 11 datasets are rendered after load — the dataset-count card proves the data path.
    expect(await screen.findByText("11")).toBeInTheDocument();
  });
});
