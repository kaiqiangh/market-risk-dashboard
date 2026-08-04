/**
 * Color family mapper tests (ADR-0002, spec #23 ticket #25).
 * Asserts the three families stay separate: risk tones only for risk semantics,
 * direction is its own muted family, freshness earns no saturated color when fresh.
 */
import { describe, expect, it } from "vitest";
import {
  dirClasses,
  dirTone,
  freshClasses,
  freshTone,
  regimeTone,
  riskLevelTone,
  riskTrendTone,
  toneClasses,
} from "@/lib/riskColors";

describe("risk family", () => {
  it("maps risk levels to risk tones (6-level enum collapses to 4 tones)", () => {
    expect(riskLevelTone("risk_on")).toBe("low");
    expect(riskLevelTone("low_risk")).toBe("low");
    expect(riskLevelTone("caution")).toBe("caution");
    expect(riskLevelTone("high_risk")).toBe("high");
    expect(riskLevelTone("severe_risk")).toBe("severe");
    expect(riskLevelTone("crisis")).toBe("severe");
  });

  it("unknown risk level falls back to na", () => {
    expect(riskLevelTone("bogus" as never)).toBe("na");
  });

  it("maps regimes to risk tones", () => {
    expect(regimeTone("goldilocks")).toBe("low");
    expect(regimeTone("late_cycle")).toBe("caution");
    expect(regimeTone("liquidity_stress")).toBe("high");
    expect(regimeTone("crisis")).toBe("severe");
    expect(regimeTone("bogus" as never)).toBe("na");
  });

  it("risk trend: rising risk = high, falling = low, null = na", () => {
    expect(riskTrendTone(1.5)).toBe("high");
    expect(riskTrendTone(-2)).toBe("low");
    expect(riskTrendTone(0)).toBe("na");
    expect(riskTrendTone(null)).toBe("na");
    expect(riskTrendTone(Number.NaN)).toBe("na");
  });

  it("risk tone classes use risk-* tokens", () => {
    expect(toneClasses("high").text).toBe("text-risk-high");
    expect(toneClasses("na").softBg).toBe("bg-risk-na/10");
  });
});

describe("direction family", () => {
  it("maps positive/negative/flat to up/down/flat", () => {
    expect(dirTone(0.5)).toBe("up");
    expect(dirTone(-0.01)).toBe("down");
    expect(dirTone(0)).toBe("flat");
    expect(dirTone(null)).toBe("flat");
    expect(dirTone(undefined)).toBe("flat");
    expect(dirTone(Number.NaN)).toBe("flat");
  });

  it("direction classes never borrow the risk ramp", () => {
    expect(dirClasses("up").text).toBe("text-dir-up");
    expect(dirClasses("down").text).toBe("text-dir-down");
    expect(dirClasses("flat").text).toBe("text-muted-foreground");
    for (const tone of ["up", "down", "flat"] as const) {
      expect(dirClasses(tone).text).not.toContain("risk-");
    }
  });
});

describe("regime family (#71)", () => {
  it("indeterminate maps to risk-na — never a risk-bearing colour", () => {
    expect(regimeTone("indeterminate")).toBe("na");
    expect(regimeTone("indeterminate")).not.toBe("high");
    expect(regimeTone("indeterminate")).not.toBe("severe");
  });
});

describe("freshness family", () => {
  it("fresh/delayed are muted; only stale and missing earn warm tones (#66/CONTEXT.md)", () => {
    expect(freshTone("fresh")).toBe("ok");
    expect(freshTone("delayed")).toBe("ok"); // live-but-delayed is a normal operational state
    expect(freshTone("degraded")).toBe("warn");
    expect(freshTone("stale")).toBe("warn");
    expect(freshTone("missing")).toBe("bad");
    expect(freshTone("bogus" as never)).toBe("na");
  });

  it("freshness classes use fresh-* tokens and never the risk ramp", () => {
    expect(freshClasses("ok").text).toBe("text-fresh-ok");
    expect(freshClasses("warn").text).toBe("text-fresh-warn");
    expect(freshClasses("bad").text).toBe("text-fresh-bad");
    for (const tone of ["ok", "warn", "bad", "na"] as const) {
      expect(freshClasses(tone).text).not.toContain("risk-");
    }
  });
});
