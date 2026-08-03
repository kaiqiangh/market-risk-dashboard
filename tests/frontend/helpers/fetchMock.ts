/**
 * 测试 fetch mock：URL → tests/fixtures/*.json（与真实数据隔离，架构 §8.12）。
 * 页面测试通过 vi.stubGlobal("fetch", installFixtureFetch()) 注入。
 */
import { vi } from "vitest";
import macroFixture from "../../fixtures/macro.json";
import equitiesFixture from "../../fixtures/equities.json";
import sectorsFixture from "../../fixtures/sectors.json";
import cryptoFixture from "../../fixtures/crypto.json";
import newsFixture from "../../fixtures/news.json";
import calendarFixture from "../../fixtures/calendar.json";
import riskFixture from "../../fixtures/risk.json";
import factsFixture from "../../fixtures/facts.json";
import analysisZhFixture from "../../fixtures/analysis.zh-CN.json";
import analysisEnFixture from "../../fixtures/analysis.en.json";
import riskHistoryFixture from "../../fixtures/risk-history-30d.json";
import marketHistoryFixture from "../../fixtures/market-history-30d.json";
import sourcesFixture from "../../fixtures/sources.json";
import freshnessFixture from "../../fixtures/freshness.json";
import schemaVersionFixture from "../../fixtures/schema-version.json";

/** URL 后缀 → fixture 映射。 */
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

/** 安装 fixture fetch（默认 200 + fixture JSON；未匹配 → 404）。 */
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

/** 安装全失败 fetch（JSON 读取失败场景）。 */
export function installFailingFetch(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("network error: data unreachable");
    }),
  );
}

/** 安装可自定义行为的 fetch（负向用例）。 */
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
