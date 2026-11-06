/**
 * Rules S1 and S2 from docs/DESIGN.md, checked against the source rather than
 * trusted to review.
 *
 * S2 is measured from the token values in globals.css, so changing a colour
 * there re-runs the contrast check on every pair that uses it, in both themes.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const CSS = readFileSync(join(ROOT, "app/globals.css"), "utf8");

/** `--name: #hex;` declarations inside the first block opened by `selector {`. */
function tokens(selector: string): Record<string, string> {
  const start = CSS.indexOf(`\n${selector} {`);
  if (start === -1) throw new Error(`no ${selector} block in globals.css`);
  const body = CSS.slice(start, CSS.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const match of body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{3,8})\s*;/gi)) {
    out[match[1]] = match[2];
  }
  return out;
}

function luminance(hex: string): number {
  let value = hex.slice(1);
  if (value.length === 3) value = [...value].map((c) => c + c).join("");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const channel = Number.parseInt(value.slice(i, i + 2), 16) / 255;
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2 contrast ratio. */
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const THEMES = { light: tokens(":root"), dark: tokens(".dark") };

/** [text, background]. Every pair is body-size text, so 4.5:1 applies. */
const PAIRS: [string, string][] = [
  ["ink", "ground"],
  ["ink", "surface"],
  ["ink-2", "ground"],
  ["ink-2", "surface"],
  ["ink-3", "ground"],
  ["ink-3", "surface"],
  ["action-ink", "action"],
  ["link", "surface"],
  ["badge-ink", "badge"],
  ["warn-ink", "warn"],
  ["age-muted", "surface"],
  ["chip-on-ink", "chip-on"],
];

describe("S1 · the palette is complete in both themes", () => {
  it("defines every token in light and redefines it in dark", () => {
    // A token declared only in one block renders the other theme's value on
    // first paint — or nothing at all.
    expect(Object.keys(THEMES.dark).sort()).toEqual(Object.keys(THEMES.light).sort());
    expect(Object.keys(THEMES.light).length).toBeGreaterThanOrEqual(19);
  });

  it("keeps the photo frame white in both themes (S5)", () => {
    expect(THEMES.light["photo-frame"].toLowerCase()).toBe("#ffffff");
    expect(THEMES.dark["photo-frame"].toLowerCase()).toBe("#ffffff");
  });
});

describe.each(Object.entries(THEMES))("S2 · contrast in the %s theme", (_, theme) => {
  it.each(PAIRS)("%s on %s reaches 4.5:1", (text, background) => {
    expect(theme[text], `--${text}`).toBeDefined();
    expect(theme[background], `--${background}`).toBeDefined();
    expect(contrast(theme[text], theme[background])).toBeGreaterThanOrEqual(4.5);
  });
});

/** Every source file under a directory, recursively. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|css|mjs)$/.test(name) ? [path] : [];
  });
}

describe("S1 · colours come only from the tokens", () => {
  // Hex literals, and the CSS colour functions. `#` followed by hex digits
  // also matches an id-looking URL fragment, so it must stand alone.
  const LITERAL =
    /(?<![\w&/-])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(/gi;

  const files = [...sources(join(ROOT, "app")), ...sources(join(ROOT, "components"))].filter(
    (path) => !path.endsWith("globals.css"),
  );

  it("finds the files it is meant to check", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it.each(files.map((path) => [relative(ROOT, path), path]))(
    "%s has no literal colour",
    (_, path) => {
      const found = readFileSync(path, "utf8").match(LITERAL) ?? [];
      expect(found, "use a token from app/globals.css instead").toEqual([]);
    },
  );
});
