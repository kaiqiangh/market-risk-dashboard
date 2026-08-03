/**
 * Design token contract test (spec #23, ticket #24).
 * Guards the token plumbing: every semantic CSS variable consumed via
 * tailwind.config.ts must be defined in BOTH the dark (default) and light
 * blocks of src/index.css — otherwise one theme silently falls back.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "../..");
const css = readFileSync(resolve(ROOT, "src/index.css"), "utf8");
const tailwindConfig = readFileSync(resolve(ROOT, "tailwind.config.ts"), "utf8");

/** var(--name) references consumed by the Tailwind semantic token mapping. */
const consumedVars = [
  ...new Set([...tailwindConfig.matchAll(/var\(--([a-z0-9-]+)\)/g)].map((m) => m[1])),
].sort();

/** Split index.css into the dark (default) block and the light override block. */
function blockVars(marker: string, endMarker: string | null): Set<string> {
  const start = css.indexOf(marker);
  expect(start, `block starting at ${marker}`).toBeGreaterThanOrEqual(0);
  const end = endMarker ? css.indexOf(endMarker, start) : css.length;
  const block = css.slice(start, end === -1 ? css.length : end);
  return new Set([...block.matchAll(/--([a-z0-9-]+)\s*:/g)].map((m) => m[1]));
}

const darkVars = blockVars(':root[class~="dark"]', ':root[class~="light"]');
const lightVars = blockVars(':root[class~="light"]', "@layer base");

/** Theme-invariant tokens defined once on plain :root, shared by both themes. */
const THEME_INVARIANT = new Set(["radius"]);

describe("design token contract", () => {
  it("tailwind config consumes CSS variables", () => {
    expect(consumedVars.length).toBeGreaterThan(10);
  });

  it.each(consumedVars.map((v) => [v]))("--%s is defined in the dark theme", (v) => {
    expect(darkVars.has(v)).toBe(true);
  });

  it.each(consumedVars.filter((v) => !THEME_INVARIANT.has(v)).map((v) => [v]))(
    "--%s is defined in the light theme",
    (v) => {
      expect(lightVars.has(v)).toBe(true);
    },
  );

  it("defines the three color families of ADR-0002 in both themes", () => {
    for (const family of ["risk-low", "risk-caution", "risk-high", "risk-severe", "risk-na", "dir-up", "dir-down", "fresh-ok", "fresh-warn", "fresh-bad"]) {
      expect(darkVars.has(family), `dark --${family}`).toBe(true);
      expect(lightVars.has(family), `light --${family}`).toBe(true);
    }
  });

  it("global radius is 4px", () => {
    expect(css).toContain("--radius: 0.25rem");
  });
});
