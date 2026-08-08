import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, beforeEach } from "vitest";
import "@/i18n";
import { fixtureForUrl, installCustomFetch, installFixtureFetch } from "./helpers/fetchMock";
import StatusPage from "@/pages/StatusPage";

/**
 * StatusPage coverage (#95 — the page previously had none): the page whose job is
 * truthfulness must render real reasons — translated codes plus the visible (not
 * tooltip-only) operator detail, in BOTH tables — from metadata VALIDATED through the
 * generated contracts, and must fail loudly when the metadata is malformed.
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

afterEach(() => {
  cleanup();
});

describe("StatusPage", () => {
  it("renders the meta cards from validated metadata", async () => {
    renderPage();
    expect(await screen.findByText("1.0.0")).toBeInTheDocument(); // schema version card
    expect(await screen.findByText("11")).toBeInTheDocument(); // 11 canonical datasets
  });

  it("renders the six-state table with translated codes and VISIBLE details", async () => {
    renderPage();
    // Statuses render from validated statuses: degraded, empty and fresh all present.
    expect((await screen.findAllByTestId("status-badge-degraded")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("status-badge-empty").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByTestId("status-badge-fresh").length).toBeGreaterThanOrEqual(1);
    // #95: every degraded widget states a specific, actionable cause — the detail is
    // rendered text on the row (a tooltip-only detail is an invisible reason). The same
    // reasons appear in the freshness table AND the providers table.
    expect(screen.getAllByText("clschina: RSS HTTP 403").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("no events in the 14-day window").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("yfinance: HTTP 429 rate limited").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the providers table with the resolved provider, degradation and cause", async () => {
    renderPage();
    expect(await screen.findByText("fred_calendar")).toBeInTheDocument(); // economic domain (#94)
    expect(screen.getAllByText("yfinance").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("provider-resolutions-market")).toHaveTextContent("yfinance");
    expect(screen.getByText("rss_news")).toBeInTheDocument();
    // A degraded provider states its specific cause in the providers table too.
    expect(screen.getByText("akshare: RemoteDisconnected")).toBeInTheDocument();
  });

  it("shows the empty state when freshness metadata has no datasets", async () => {
    installCustomFetch((url) => {
      if (url.endsWith("/metadata/freshness.json")) {
        return { ok: true, body: { schema_version: "1.0.0", updated_at: "2026-08-07T09:00:00Z", datasets: {} } };
      }
      const r = fixtureForUrl(url);
      return { ok: r.ok, body: r.body };
    });
    renderPage();
    expect(await screen.findByTestId("status-freshness-empty")).toBeInTheDocument();
  });

  it("fails loudly when the metadata does not match the generated contract", async () => {
    // #95: the page validates like every other page — a malformed status is a SchemaError
    // → the freshness section renders the error state, not a silently trusted cast.
    installCustomFetch((url) => {
      if (url.endsWith("/metadata/freshness.json")) {
        return {
          ok: true,
          body: {
            schema_version: "1.0.0",
            updated_at: "2026-08-07T09:00:00Z",
            datasets: { equities: { status: "not-a-status", reason: { code: "ok", detail: "" }, updated_at: "2026-08-07T09:00:00Z" } },
          },
        };
      }
      const r = fixtureForUrl(url);
      return { ok: r.ok, body: r.body };
    });
    renderPage();
    // The page's metadata queries carry retry: 1 (one ~1s backoff retry), so the
    // rejected freshness fetch settles after the retry window — wait past it.
    expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toBeInTheDocument();
  });
});
