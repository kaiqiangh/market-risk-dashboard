/**
 * Test fetch mock: URL → tests/fixtures/*.json (isolated from real data, architecture §8.12).
 * Page tests inject it via vi.stubGlobal("fetch", installFixtureFetch()).
 */
import { vi } from "vitest";
import riskFixture from "../../fixtures/risk.json";
import factsFixture from "../../fixtures/facts.json";
import analysisZhFixture from "../../fixtures/analysis.zh-CN.json";
import {
  analysisEnFixture,
  calendarFixture,
  cryptoFixture,
  equitiesFixture,
  freshnessFixture,
  macroFixture,
  marketHistory30dFixture as marketHistoryFixture,
  newsFixture,
  riskHistory30dFixture as riskHistoryFixture,
  schemaVersionFixture,
  sectorsFixture,
  sourcesFixture,
} from "./fixtureData";

/** URL suffix → fixture mapping. */
export const FIXTURE_MAP: Record<string, unknown> = {
  "/latest/macro.json": macroFixture,
  "/latest/equities.json": equitiesFixture,
  "/latest/sectors.json": sectorsFixture,
  "/latest/crypto.json": cryptoFixture,
  "/latest/news.json": newsFixture,
  "/latest/calendar.json": calendarFixture,
  "/latest/risk.json": riskFixture,
  "/latest/facts.json": factsFixture,
  "/latest/analysis.zh-CN.json": analysisZhFixture,
  "/latest/analysis.en.json": analysisEnFixture,
  "/history/risk/30d.json": riskHistoryFixture,
  "/history/market/30d.json": marketHistoryFixture,
  "/metadata/sources.json": sourcesFixture,
  "/metadata/freshness.json": freshnessFixture,
  "/metadata/schema-version.json": schemaVersionFixture,
};

export function fixtureForUrl(url: string): { ok: boolean; body: unknown } {
  const path = url.replace(/^https?:\/\/[^/]+/, "");
  for (const [suffix, body] of Object.entries(FIXTURE_MAP)) {
    if (path.endsWith(suffix)) {
      return { ok: true, body };
    }
  }
  return { ok: false, body: { error: "fixture not found", path } };
}

/** Install fixture fetch (default 200 + fixture JSON; unmatched → 404). */
export function installFixtureFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const { ok, body } = fixtureForUrl(url);
      if (!ok) {
        return new Response(JSON.stringify({ error: "not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

/** Install an always-failing fetch (JSON read failure scenario). */
export function installFailingFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("network error: data unreachable");
    }),
  );
}

/** Install a customizable fetch (negative cases). */
export function installCustomFetch(handler: (url: string) => { ok: boolean; body?: unknown }): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const result = handler(url);
      if (!result.ok) {
        return new Response(JSON.stringify({ error: "not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(result.body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}
