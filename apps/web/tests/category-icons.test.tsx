/**
 * Rule S7 from docs/DESIGN.md: every category icon is drawn to the set's style,
 * and Electronics, the first department with a drawn set, has one for every
 * group and category in its taxonomy.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CATEGORY_ICONS,
  CategoryIcon,
  categoryGlyph,
  DEPARTMENTS_WITH_ICONS,
  hasCategoryIcons,
  tileIcon,
} from "@/components/category-icons";
import { departmentIcon } from "@/components/department-icon";

const ENTRIES = Object.entries(CATEGORY_ICONS);

function svgOf(ref: string): SVGSVGElement {
  const html = renderToStaticMarkup(<CategoryIcon iconRef={ref} />);
  const doc = new DOMParser().parseFromString(html, "image/svg+xml");
  return doc.documentElement as unknown as SVGSVGElement;
}

/** Every point a path's commands land on (arc and curve end points, not their bulge). */
function pathPoints(d: string): [number, number][] {
  const tokens = d.match(/[a-zA-Z]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?/g) ?? [];
  const points: [number, number][] = [];
  let x = 0;
  let y = 0;
  let startX = 0;
  let startY = 0;
  let command = "";
  let i = 0;
  const num = () => Number(tokens[i++]);
  const arity: Record<string, number> = {
    m: 2,
    l: 2,
    h: 1,
    v: 1,
    c: 6,
    s: 4,
    q: 4,
    t: 2,
    a: 7,
    z: 0,
  };
  while (i < tokens.length) {
    if (/[a-zA-Z]/.test(tokens[i])) command = tokens[i++];
    const lower = command.toLowerCase();
    const rel = command !== command.toUpperCase();
    if (!(lower in arity)) throw new Error(`unknown path command ${command} in ${d}`);
    if (lower === "z") {
      [x, y] = [startX, startY];
      continue;
    }
    const args = Array.from({ length: arity[lower] }, num);
    if (args.some(Number.isNaN)) throw new Error(`bad path data: ${d}`);
    if (lower === "h") x = rel ? x + args[0] : args[0];
    else if (lower === "v") y = rel ? y + args[0] : args[0];
    else {
      const [ex, ey] = args.slice(-2);
      x = rel ? x + ex : ex;
      y = rel ? y + ey : ey;
    }
    if (lower === "m") {
      [startX, startY] = [x, y];
      // Coordinates after a moveto are implicit linetos.
      command = rel ? "l" : "L";
    }
    points.push([x, y]);
  }
  return points;
}

describe("S7 · every category icon follows the style guide", () => {
  it("has icons to check", () => {
    expect(ENTRIES.length).toBeGreaterThanOrEqual(50);
  });

  it.each(ENTRIES)("%s: one 1.5 stroke, round, unfilled, currentColor, on 24 × 24", (ref) => {
    const svg = svgOf(ref);
    expect(svg.tagName).toBe("svg");
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("fill")).toBe("none");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-width")).toBe("1.5");
    expect(svg.getAttribute("stroke-linecap")).toBe("round");
    expect(svg.getAttribute("stroke-linejoin")).toBe("round");
    expect(svg.getAttribute("aria-hidden")).toBe("true");

    const shapes = [...svg.querySelectorAll("*")];
    expect(shapes.length).toBeGreaterThan(0);
    for (const shape of shapes) {
      // Plain shapes only: no groups with transforms, no text, no images.
      expect(["path", "rect", "circle", "line", "ellipse"], ref).toContain(shape.tagName);
      for (const { name, value } of [...shape.attributes]) {
        // Nothing may restyle a stroke: weight, caps, colour and fill all come from the <svg>.
        expect(
          ["d", "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "x1", "y1", "x2", "y2"],
          `${ref}: <${shape.tagName} ${name}="${value}">`,
        ).toContain(name);
      }
      const fill = shape.getAttribute("fill");
      expect(fill === null || fill === "none" || fill === "currentColor").toBe(true);
    }
  });

  it.each(ENTRIES)(
    "%s stays on the grid: shapes in the 2-unit margin, leads to the edge",
    (ref, glyph) => {
      const svg = svgOf(ref);
      const LIVE: [number, number] = [2, 22];
      // A category's schematic leads may run to the edge, as a wire would; an object may not.
      const reach: [number, number] = glyph.kind === "category" ? [0, 24] : LIVE;
      const inside = ([lo, hi]: [number, number], ...values: number[]) =>
        values.every((v) => v >= lo - 1e-6 && v <= hi + 1e-6);

      for (const rect of svg.querySelectorAll("rect")) {
        const [x, y, w, h] = ["x", "y", "width", "height"].map((a) => Number(rect.getAttribute(a)));
        expect(inside(LIVE, x, y, x + w, y + h), `${ref}: rect ${x},${y} ${w}×${h}`).toBe(true);
      }
      for (const circle of svg.querySelectorAll("circle")) {
        const [cx, cy, r] = ["cx", "cy", "r"].map((a) => Number(circle.getAttribute(a)));
        expect(inside(LIVE, cx - r, cy - r, cx + r, cy + r), `${ref}: circle at ${cx},${cy}`).toBe(
          true,
        );
      }
      for (const ellipse of svg.querySelectorAll("ellipse")) {
        const [cx, cy, rx, ry] = ["cx", "cy", "rx", "ry"].map((a) =>
          Number(ellipse.getAttribute(a)),
        );
        expect(inside(LIVE, cx - rx, cy - ry, cx + rx, cy + ry), `${ref}: ellipse`).toBe(true);
      }
      for (const path of svg.querySelectorAll("path")) {
        for (const [x, y] of pathPoints(path.getAttribute("d") ?? "")) {
          expect(inside(reach, x, y), `${ref}: point ${x.toFixed(2)},${y.toFixed(2)}`).toBe(true);
        }
      }
    },
  );
});

const DOMAINS = join(__dirname, "../../../packages/schemas/makhzan_schemas/domains");

/**
 * (slug, parent slug or null) for every category in a department's Python
 * taxonomy, or null when the department's profile is not in this checkout.
 */
function taxonomyOf(domain: string): [string, string | null][] | null {
  const path = join(DOMAINS, `${domain.replace(/-/g, "_")}.py`);
  if (!existsSync(path)) return null;
  const source = readFileSync(path, "utf8");
  const block = source.slice(
    source.indexOf("TAXONOMY"),
    source.indexOf("]\n", source.indexOf("TAXONOMY")),
  );
  return [
    ...block.matchAll(/\(\s*"([a-z0-9-]+)",\s*"[^"]*",\s*"[^"]*",\s*(None|"([a-z0-9-]+)")\s*\)/g),
  ].map((m) => [m[1], m[3] ?? null]);
}

describe("S7 · a drawn department has an icon for every group and category", () => {
  it("reads Electronics' taxonomy", () => {
    const taxonomy = taxonomyOf("electronics")!;
    expect(taxonomy.length).toBeGreaterThanOrEqual(40);
    expect(taxonomy.filter(([, parent]) => parent === null)).toHaveLength(8);
  });

  // Every department with any icon drawn, checked against its taxonomy when
  // its profile is in this checkout. A department drawn ahead of its taxonomy
  // (photography, before feat/taxonomy-gaps merges) is checked once it lands.
  const rows = [...DEPARTMENTS_WITH_ICONS].flatMap((domain) =>
    (taxonomyOf(domain) ?? []).map(([slug, parent]) => [`${domain}:${slug}`, parent] as const),
  );

  it.each(rows)("%s is drawn", (ref, parent) => {
    const glyph = categoryGlyph(ref);
    expect(glyph, `draw ${ref} in components/category-icons.tsx`).not.toBeNull();
    // Groups are objects, categories symbols: the two families must not swap.
    expect(glyph?.kind).toBe(parent === null ? "group" : "category");
  });

  it("allows icons drawn ahead of the taxonomy, and says which they are", () => {
    // An icon for a ref the taxonomy does not have yet is not an error: the
    // icons for feat/taxonomy-gaps' categories are drawn before it merges.
    // Only a category without an icon is (above).
    const known = new Set<string>(rows.map(([ref]) => ref));
    const ahead = Object.keys(CATEGORY_ICONS).filter((ref) => !known.has(ref));
    const expected = [
      "electronics:cameras",
      "electronics:kits",
      "photography:lighting",
      "photography:camera-gear",
      "photography:photo-lights",
      "photography:tripods",
      "photography:camera-bags",
      "photography:camera-accessories",
    ];
    // Once a taxonomy lands, its refs leave this list; nothing else may be in it.
    for (const ref of ahead) expect(expected, ref).toContain(ref);
  });
});

describe("the registry is keyed by ref, and falls back cleanly", () => {
  it("keys every icon by domain:slug", () => {
    for (const ref of Object.keys(CATEGORY_ICONS)) expect(ref).toMatch(/^[a-z0-9-]+:[a-z0-9-]+$/);
  });

  it("never matches a bare slug, nor another department's same slug", () => {
    expect(categoryGlyph("measurement")).toBeNull();
    expect(categoryGlyph("electronics:measurement")).not.toBeNull();
    expect(categoryGlyph("tools:measurement")).toBeNull();
    expect(categoryGlyph("toString")).toBeNull();
  });

  it("knows which departments are drawn", () => {
    expect([...DEPARTMENTS_WITH_ICONS]).toEqual(["electronics", "photography"]);
    expect(hasCategoryIcons("electronics")).toBe(true);
    expect(hasCategoryIcons("seals-bearings")).toBe(false);
  });

  it("renders nothing for a category it has not drawn", () => {
    expect(renderToStaticMarkup(<CategoryIcon iconRef="electronics:not-drawn" />)).toBe("");
  });

  it("gives an undrawn group tile its department's icon", () => {
    expect(tileIcon("seals-bearings:seals", "seals-bearings")).toBe(
      departmentIcon("seals-bearings"),
    );
    expect(tileIcon("electronics:power", "electronics")).not.toBe(departmentIcon("electronics"));
    const Tile = tileIcon("electronics:power", "electronics");
    expect(renderToStaticMarkup(<Tile className="x" strokeWidth={1.25} />)).toContain(
      'stroke-width="1.5"',
    );
  });
});
