/**
 * Rules C4 and S3 from docs/DESIGN.md, checked against the source and the
 * rendered components rather than trusted to review.
 */
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

import { PriceRange } from "@/components/price";

const ROOT = join(__dirname, "..");
const CSS = readFileSync(join(ROOT, "app/globals.css"), "utf8");

/** Every .ts/.tsx file under a directory, recursively. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

const FILES = [...sources(join(ROOT, "app")), ...sources(join(ROOT, "components"))];

/** The source with its comments blanked out: block comments (JSX ones
 *  included) and line comments, but not the `//` inside a URL. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\w])\/\/.*$/gm, "$1");
}

/** The opening tag an expression at `index` sits in or under: the text from
 *  the last `<` before it. */
function enclosingTag(source: string, index: number): string {
  const start = source.lastIndexOf("<", index);
  return source.slice(start, index);
}

describe("C4 · no Arabic interface text", () => {
  // Arabic, Arabic Supplement, Extended-A and both presentation-form blocks.
  // Supplier data may be Arabic (titles, queries); the interface may not.
  const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/;

  it("finds the files it is meant to check", () => {
    expect(FILES.length).toBeGreaterThan(20);
  });

  it("knows Arabic when it sees it, and ignores it in comments", () => {
    expect(ARABIC.test(withoutComments('const label = "بحث";'))).toBe(true);
    expect(ARABIC.test(withoutComments("// بحث\n/* بحث */ const x = 1;"))).toBe(false);
  });

  it.each(FILES.map((path) => [relative(ROOT, path), path]))(
    "%s has no Arabic outside comments",
    (_, path) => {
      const lines = withoutComments(readFileSync(path, "utf8"))
        .split("\n")
        .filter((line) => ARABIC.test(line));
      expect(lines, "the interface is English only (docs/DESIGN.md, C4)").toEqual([]);
    },
  );
});

describe("S3 · prices use tabular figures, part numbers the monospace face", () => {
  it("defines the figure utility as tabular Archivo", () => {
    const figure = CSS.slice(
      CSS.indexOf("@utility figure"),
      CSS.indexOf("}", CSS.indexOf("@utility figure")),
    );
    expect(figure).toContain("font-variant-numeric: tabular-nums");
    expect(figure).toContain("var(--font-display)");
  });

  it("styles every [data-identifier] in the monospace face", () => {
    const start = CSS.indexOf("[data-identifier] {");
    expect(start).toBeGreaterThan(-1);
    expect(CSS.slice(start, CSS.indexOf("}", start))).toContain("var(--font-mono)");
  });

  it("renders a price with the figure class", () => {
    const { container } = render(<PriceRange min={260} max={400} currency="EGP" />);
    const price = container.querySelector("[data-price]");
    expect(price).toHaveTextContent("EGP 260 – 400");
    expect(price).toHaveClass("figure");
  });

  // Anywhere a price is formatted straight into markup, rather than through
  // PriceRange, the element holding it must still carry the figure or the
  // tabular class. Formatting into a string (a label, a description) is fine.
  it.each(FILES.map((path) => [relative(ROOT, path), path]))(
    "%s puts formatted prices only in tabular elements",
    (_, path) => {
      const source = withoutComments(readFileSync(path, "utf8"));
      const bad = [...source.matchAll(/>\s*\{\s*formatPrice(?:Range)?\(/g)]
        .map((match) => enclosingTag(source, match.index))
        .filter((tag) => !/\b(figure|tabular)\b|data-price/.test(tag));
      expect(bad).toEqual([]);
    },
  );

  it.each(FILES.map((path) => [relative(ROOT, path), path]))(
    "%s marks every rendered part number with data-identifier",
    (_, path) => {
      const source = withoutComments(readFileSync(path, "utf8"));
      // `{product.part_number}` as a child, not `x.part_number ||` in code.
      const bad = [...source.matchAll(/>\s*\{[\w.?]*part_number\}/g)]
        .map((match) => enclosingTag(source, match.index))
        .filter((tag) => !tag.includes("data-identifier"));
      expect(bad).toEqual([]);
    },
  );

  it("would catch a part number rendered without it", () => {
    const source = '<span className="text-ink">{product.part_number}</span>';
    const match = /> *\{[\w.?]*part_number\}/.exec(source)!;
    expect(enclosingTag(source, match.index)).not.toContain("data-identifier");
  });
});
