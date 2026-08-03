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

  it("every color token is rgb()-wrapped in the tailwind config (bugfix: bare var() triplets render transparent)", () => {
    // radius is a layout token (bare var() is correct there) — only color tokens need the wrapper
    const colorRefs = consumedVars.filter((v) => !THEME_INVARIANT.has(v));
    expect(colorRefs.length).toBeGreaterThan(10);
    // Bare `var(--x)` as background-color resolves to "255 255 255", which is NOT a
    // valid color — surfaces render transparent. All color utilities must emit
    // `rgb(var(--x) / <alpha-value>)` so both `bg-card` and `bg-card/10` are valid.
    for (const v of colorRefs) {
      const ref = `var(--${v})`;
      expect(tailwindConfig, `rgb() wrapper around ${ref}`).toContain(`rgb(${ref} / <alpha-value>)`);
    }
  });
});

/* ---------- WCAG AA contrast audit (spec #23 ticket #34) ---------- */

type RGB = [number, number, number];

function parseVars(block: string): Map<string, RGB> {
  const out = new Map<string, RGB>();
  for (const m of block.matchAll(/--([a-z0-9-]+):\s*([0-9]+)\s+([0-9]+)\s+([0-9]+)/g)) {
    out.set(m[1], [Number(m[2]), Number(m[3]), Number(m[4])]);
  }
  return out;
}

function luminance([r, g, b]: RGB): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(a: RGB, b: RGB): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

const darkBlock = css.slice(css.indexOf(':root[class~="dark"]'), css.indexOf(':root[class~="light"]'));
const lightBlock = css.slice(css.indexOf(':root[class~="light"]'), css.indexOf("@layer base"));
const darkTokens = parseVars(darkBlock);
const lightTokens = parseVars(lightBlock);

/** Text/UI pairings that must meet 4.5:1 in both themes. */
const AA_PAIRS: [string, string][] = [
  ["foreground", "surface-0"],
  ["foreground", "surface-1"],
  ["foreground", "surface-2"],
  ["muted-foreground", "surface-0"],
  ["muted-foreground", "surface-1"],
  ["muted-foreground", "surface-2"],
  ["primary", "surface-0"],
  ["primary", "surface-1"],
  ["primary-foreground", "primary"],
  ["dir-up", "surface-0"],
  ["dir-up", "surface-1"],
  ["dir-down", "surface-0"],
  ["dir-down", "surface-1"],
  ["risk-low", "surface-0"],
  ["risk-low", "surface-1"],
  ["risk-caution", "surface-0"],
  ["risk-caution", "surface-1"],
  ["risk-high", "surface-0"],
  ["risk-high", "surface-1"],
  ["risk-severe", "surface-0"],
  ["risk-severe", "surface-1"],
  ["risk-na", "surface-1"],
  ["fresh-warn", "surface-1"],
  ["fresh-bad", "surface-1"],
];

describe("WCAG AA contrast (ticket #34)", () => {
  for (const [theme, tokens] of [
    ["dark", darkTokens],
    ["light", lightTokens],
  ] as const) {
    it.each(AA_PAIRS.map(([fg, bg]) => [fg, bg] as [string, string]))(
      `[${theme}] %s on %s meets 4.5:1`,
      (fg, bg) => {
        const fgRgb = tokens.get(fg);
        const bgRgb = tokens.get(bg);
        expect(fgRgb, `${fg} defined`).toBeDefined();
        expect(bgRgb, `${bg} defined`).toBeDefined();
        expect(contrast(fgRgb!, bgRgb!)).toBeGreaterThanOrEqual(4.5);
      },
    );
  }
});
