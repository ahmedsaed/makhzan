/**
 * The brand's colours live in two places: the CSS tokens, which components
 * use (rule S1), and lib/brand.ts, for the link-preview cards and the icons,
 * which cannot read CSS. These tests keep the copies equal, so a palette
 * change cannot leave the cards or the favicon in the old colours.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Logo } from "@/components/logo";
import { darkPalette, markSvg, palette } from "@/lib/brand";

const ROOT = join(__dirname, "..");
const CSS = readFileSync(join(ROOT, "app/globals.css"), "utf8");

function token(selector: string, name: string): string {
  const start = CSS.indexOf(`\n${selector} {`);
  const body = CSS.slice(start, CSS.indexOf("}", start));
  const match = new RegExp(`--${name}:\\s*(#[0-9a-f]{3,8})\\s*;`, "i").exec(body);
  if (!match) throw new Error(`no --${name} in ${selector}`);
  return match[1].toLowerCase();
}

describe("brand colours match the tokens", () => {
  it.each([
    ["ground", palette.ground],
    ["surface", palette.surface],
    ["ink", palette.ink],
    ["ink-2", palette.ink2],
    ["line", palette.line],
    ["brand", palette.brand],
    ["photo-frame", palette.photoFrame],
  ])("light --%s", (name, value) => {
    expect(value).toBe(token(":root", name));
  });

  it.each([
    ["ground", darkPalette.ground],
    ["ink", darkPalette.ink],
  ])("dark --%s", (name, value) => {
    expect(value).toBe(token(".dark", name));
  });

  it("draws the tab icon in the light ink, the dark ink in a dark tab bar, and the brand", () => {
    const svg = readFileSync(join(ROOT, "app/icon.svg"), "utf8").toLowerCase();
    const dark = svg.slice(svg.indexOf("prefers-color-scheme: dark"));
    expect(svg).toContain(palette.ink);
    expect(svg).toContain(palette.brand);
    expect(dark).toContain(darkPalette.ink);
  });
});

describe("the mark", () => {
  it("is three outlined compartments and one filled, top right", () => {
    const svg = markSvg();
    expect(svg.match(/fill="none"/g)).toHaveLength(3);
    expect(svg).toContain(
      `<rect x="26" y="4" width="18" height="18" rx="4" fill="${palette.brand}"/>`,
    );
  });

  it("takes its ink from the text around it in the page, and its fill from the token", () => {
    const { container } = render(<Logo />);
    const rects = [...container.querySelectorAll("rect")];
    expect(rects.filter((rect) => rect.getAttribute("stroke") === "currentColor")).toHaveLength(3);
    expect(rects.filter((rect) => rect.classList.contains("fill-brand"))).toHaveLength(1);
    expect(container.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(container.textContent).toBe("makhzan");
  });
});
