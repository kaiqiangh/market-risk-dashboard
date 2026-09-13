import { afterEach, describe, expect, it, vi } from "vitest";
import { DATA_REQUEST_TIMEOUT_MS, DatasetClient } from "@/lib/api";
import { macroFixture } from "./helpers/fixtureData";

const client = new DatasetClient("/");

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("DatasetClient request lifecycle", () => {
  it("passes the React Query abort signal to fetch", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      return new Response(JSON.stringify(macroFixture), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;

    await client.fetch("macro", {}, undefined, signal);

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("aborts and reports a bounded request timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const pending = client.fetch("macro");
    const timedOut = expect(pending).rejects.toThrow("Data request timed out");
    await vi.advanceTimersByTimeAsync(DATA_REQUEST_TIMEOUT_MS);

    await timedOut;
    expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });

  it("preserves caller cancellation instead of relabelling it as a timeout", async () => {
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const pending = client.fetch("macro", {}, undefined, controller.signal);
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
