import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, beforeEach } from "vitest";
import "@/i18n";
import { installFixtureFetch } from "./helpers/fetchMock";
import MacroPage from "@/pages/MacroPage";

/**
 * MacroPage coverage (#96 — the page previously had no tests): the eight sections all
 * render (incl. the new `volatility` group for VIX), and the per-group 30d history
 * section charts the sparse bundles (HTML fallback in jsdom).
 */

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MacroPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  installFixtureFetch();
});

afterEach(() => {
  cleanup();
});

describe("MacroPage", () => {
  it("renders all eight sections including the volatility group", async () => {
    renderPage();
    // All seven indicator sections render (every one is populated in the fixture).
    for (const section of ["rates", "credit", "volatility", "inflation", "labor", "liquidity", "fx"]) {
      expect(await screen.findByTestId(`section-${section}`)).toBeInTheDocument();
    }
    // The volatility section carries the VIX indicator (moved out of rates, #84 §5) —
    // it also appears in the cross-sectional chart, so match both.
    expect(screen.getAllByText("波动率指数").length).toBeGreaterThanOrEqual(1);
    // Rates still render the 10Y (card + chart).
    expect(screen.getAllByText("十年期国债收益率").length).toBeGreaterThanOrEqual(1);
  });

  it("charts the selected group's 30d history from the sparse bundle", async () => {
    renderPage();
    // History section renders; default group is fx → the bundle fallback table shows the
    // series names (jsdom has no canvas → HTML fallback is the testable surface).
    const historySection = await screen.findByTestId("section-history");
    expect(historySection).toBeInTheDocument();
    expect(await screen.findByTestId("macro-history-fallback")).toBeInTheDocument();
    expect(screen.getByText("DTWEXBGS")).toBeInTheDocument();
    expect(screen.getByText("DEXUSEU")).toBeInTheDocument();
  });

  it("switches the history window to 90d (consuming the 90d bundles, #84 §3)", async () => {
    renderPage();
    await screen.findByTestId("macro-history-fallback");
    // The 30d/90d toggle is the consumer that keeps the 90d bundles live data.
    fireEvent.click(screen.getByRole("button", { name: "90d" }));
    expect(await screen.findByTestId("macro-history-fallback")).toBeInTheDocument();
    expect(screen.getByText("DTWEXBGS")).toBeInTheDocument();
  });
});
