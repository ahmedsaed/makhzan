/**
 * Rule S7 from docs/DESIGN.md: every category icon is drawn to the set's style,
 * every department's taxonomy has an icon for each group and category, and no
 * icon is drawn for a ref no taxonomy has.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
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

const SAMPLES = 24;

/** Points along an SVG arc (endpoint form, SVG 1.1 implementation notes F.6.5). */
function arcPoints(
  [x1, y1]: [number, number],
  [rx0, ry0, rot, large, sweep, x2, y2]: number[],
): [number, number][] {
  let rx = Math.abs(rx0);
  let ry = Math.abs(ry0);
  if (rx === 0 || ry === 0 || (x1 === x2 && y1 === y2)) return [[x2, y2]];
  const phi = (rot * Math.PI) / 180;
  const [cp, sp] = [Math.cos(phi), Math.sin(phi)];
  const dx = (x1 - x2) / 2;
  const dy = (y1 - y2) / 2;
  const x1p = cp * dx + sp * dy;
  const y1p = -sp * dx + cp * dy;
  const lambda = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
  if (lambda > 1) {
    rx *= Math.sqrt(lambda);
    ry *= Math.sqrt(lambda);
  }
  const num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
  const den = rx * rx * y1p * y1p + ry * ry * x1p * x1p;
  const k = (large === sweep ? -1 : 1) * Math.sqrt(Math.max(0, num / den));
  const cxp = (k * rx * y1p) / ry;
  const cyp = (-k * ry * x1p) / rx;
  const cx = cp * cxp - sp * cyp + (x1 + x2) / 2;
  const cy = sp * cxp + cp * cyp + (y1 + y2) / 2;
  const angle = (ux: number, uy: number, vx: number, vy: number) =>
    Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  const t1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
  let dt = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
  if (!sweep && dt > 0) dt -= 2 * Math.PI;
  if (sweep && dt < 0) dt += 2 * Math.PI;
  return Array.from({ length: SAMPLES }, (_, n) => {
    const t = t1 + (dt * (n + 1)) / SAMPLES;
    return [
      cp * rx * Math.cos(t) - sp * ry * Math.sin(t) + cx,
      sp * rx * Math.cos(t) + cp * ry * Math.sin(t) + cy,
    ] as [number, number];
  });
}

/** Points along a Bezier of any order, by de Casteljau. */
function bezierPoints(control: [number, number][]): [number, number][] {
  return Array.from({ length: SAMPLES }, (_, n) => {
    const t = (n + 1) / SAMPLES;
    let pts = control;
    while (pts.length > 1) {
      pts = pts
        .slice(1)
        .map((p, j) => [pts[j][0] + (p[0] - pts[j][0]) * t, pts[j][1] + (p[1] - pts[j][1]) * t]);
    }
    return pts[0];
  });
}

/**
 * Points along a path's real geometry: line ends, and samples along every cubic,
 * quadratic and arc segment, so a bulge that leaves the live area is seen.
 */
function pathPoints(d: string): [number, number, boolean][] {
  const tokens = d.match(/[a-zA-Z]|-?(?:\d+\.?\d*|\.\d+)(?:e-?\d+)?/g) ?? [];
  const points: [number, number, boolean][] = [];
  let x = 0;
  let y = 0;
  let startX = 0;
  let startY = 0;
  let command = "";
  // The last control point, which S and T reflect.
  let lastCtrl: [number, number] | null = null;
  let lastKind = "";
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
      lastKind = "";
      continue;
    }
    const args = Array.from({ length: arity[lower] }, num);
    if (args.some(Number.isNaN)) throw new Error(`bad path data: ${d}`);
    const ox = rel ? x : 0;
    const oy = rel ? y : 0;
    const from: [number, number] = [x, y];
    let kind = "";
    if (lower === "h") {
      x = ox + args[0];
      points.push([x, y, false]);
    } else if (lower === "v") {
      y = oy + args[0];
      points.push([x, y, false]);
    } else if (lower === "c" || lower === "s") {
      const [c1, c2, end]: [number, number][] =
        lower === "c"
          ? [
              [ox + args[0], oy + args[1]],
              [ox + args[2], oy + args[3]],
              [ox + args[4], oy + args[5]],
            ]
          : [
              lastKind === "c" && lastCtrl ? [2 * x - lastCtrl[0], 2 * y - lastCtrl[1]] : [x, y],
              [ox + args[0], oy + args[1]],
              [ox + args[2], oy + args[3]],
            ];
      points.push(
        ...bezierPoints([from, c1, c2, end]).map(([a, b]): [number, number, boolean] => [
          a,
          b,
          true,
        ]),
      );
      [x, y] = end;
      lastCtrl = c2;
      kind = "c";
    } else if (lower === "q" || lower === "t") {
      const [c1, end]: [number, number][] =
        lower === "q"
          ? [
              [ox + args[0], oy + args[1]],
              [ox + args[2], oy + args[3]],
            ]
          : [
              lastKind === "q" && lastCtrl ? [2 * x - lastCtrl[0], 2 * y - lastCtrl[1]] : [x, y],
              [ox + args[0], oy + args[1]],
            ];
      points.push(
        ...bezierPoints([from, c1, end]).map(([a, b]): [number, number, boolean] => [a, b, true]),
      );
      [x, y] = end;
      lastCtrl = c1;
      kind = "q";
    } else if (lower === "a") {
      const end: [number, number] = [ox + args[5], oy + args[6]];
      points.push(
        ...arcPoints(from, [...args.slice(0, 5), ...end]).map(
          ([a, b]): [number, number, boolean] => [a, b, true],
        ),
      );
      [x, y] = end;
    } else {
      x = ox + args[0];
      y = oy + args[1];
      points.push([x, y, false]);
      if (lower === "m") {
        [startX, startY] = [x, y];
        // Coordinates after a moveto are implicit linetos.
        command = rel ? "l" : "L";
      }
    }
    lastKind = kind;
  }
  return points;
}

const ATTRIBUTES = [
  "d",
  "x",
  "y",
  "width",
  "height",
  "rx",
  "ry",
  "cx",
  "cy",
  "r",
  "x1",
  "y1",
  "x2",
  "y2",
];

/**
 * Every place a shape's geometry (curves and arcs sampled) leaves the live area. A
 * straight segment's end may reach `lead` (a lead runs on to the edge); a curve or arc
 * may not, so a bulge or a wave cannot hide in the margin.
 */
function outsideLiveArea(
  svg: Element,
  [lo, hi]: [number, number],
  lead: [number, number] = [lo, hi],
): string[] {
  const out: string[] = [];
  const check = (what: string, ...values: number[]) => {
    if (!values.every((v) => v >= lo - 1e-6 && v <= hi + 1e-6)) out.push(what);
  };
  const n = (el: Element, ...names: string[]) => names.map((a) => Number(el.getAttribute(a)));
  for (const rect of svg.querySelectorAll("rect")) {
    const [x, y, w, h] = n(rect, "x", "y", "width", "height");
    check(`rect ${x},${y} ${w}×${h}`, x, y, x + w, y + h);
  }
  for (const circle of svg.querySelectorAll("circle")) {
    const [cx, cy, r] = n(circle, "cx", "cy", "r");
    check(`circle at ${cx},${cy}`, cx - r, cy - r, cx + r, cy + r);
  }
  for (const ellipse of svg.querySelectorAll("ellipse")) {
    const [cx, cy, rx, ry] = n(ellipse, "cx", "cy", "rx", "ry");
    check(`ellipse at ${cx},${cy}`, cx - rx, cy - ry, cx + rx, cy + ry);
  }
  for (const line of svg.querySelectorAll("line")) {
    const [x1, y1, x2, y2] = n(line, "x1", "y1", "x2", "y2");
    check(`line ${x1},${y1} ${x2},${y2}`, x1, y1, x2, y2);
  }
  for (const path of svg.querySelectorAll("path")) {
    for (const [x, y, curved] of pathPoints(path.getAttribute("d") ?? "")) {
      const [a, b] = curved ? [lo, hi] : lead;
      if (![x, y].every((v) => v >= a - 1e-6 && v <= b + 1e-6)) {
        out.push(`${curved ? "curve" : "point"} ${x.toFixed(2)},${y.toFixed(2)}`);
      }
    }
  }
  return out;
}

describe("S7 · every category icon follows the style guide", () => {
  it("has icons to check", () => {
    expect(ENTRIES.length).toBeGreaterThanOrEqual(150);
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
        expect(ATTRIBUTES, `${ref}: <${shape.tagName} ${name}="${value}">`).toContain(name);
      }
    }
  });

  it.each(ENTRIES)(
    "%s stays on the grid: shapes in the 2-unit margin, leads to the edge",
    (ref, glyph) => {
      // A category's leads (a wire, hose, cable, pipe stub, port or spray leaving the
      // object) may run to the edge; a group, an object, may not.
      const lead: [number, number] = glyph.kind === "category" ? [0, 24] : [2, 22];
      expect(outsideLiveArea(svgOf(ref), [2, 22], lead), ref).toEqual([]);
    },
  );
});

const DOMAINS = join(__dirname, "../../../packages/schemas/makhzan_schemas/domains");

/**
 * (slug, parent slug or null) for every category in a department's Python
 * taxonomy, or null when the department's profile is not in this checkout.
 *
 * Read from the source, so the web suite needs no Python. The regex is
 * cross-checked against the block's tuple lines: if a tuple is ever written
 * in a shape it does not read (a trailing comment, a split line), the counts
 * differ and this throws, rather than the coverage test passing on fewer rows.
 */
function taxonomyOf(domain: string): [string, string | null][] | null {
  const path = join(DOMAINS, `${domain.replace(/-/g, "_")}.py`);
  if (!existsSync(path)) return null;
  const source = readFileSync(path, "utf8");
  const at = source.search(/^TAXONOMY\b/m);
  if (at === -1) throw new Error(`${path}: no TAXONOMY`);
  const block = source.slice(at, source.indexOf("\n]", at));
  const rows = [
    ...block.matchAll(/\(\s*"([a-z0-9-]+)",\s*"[^"]*",\s*"[^"]*",\s*(None|"([a-z0-9-]+)"),?\s*\)/g),
  ].map((m): [string, string | null] => [m[1], m[3] ?? null]);
  const tupleLines = block.split("\n").filter((line) => /^\s*\(/.test(line)).length;
  if (rows.length !== tupleLines) {
    throw new Error(`${path}: read ${rows.length} categories from ${tupleLines} tuple lines`);
  }
  return rows;
}

describe("S7 · a drawn department has an icon for every group and category", () => {
  const departments = [...DEPARTMENTS_WITH_ICONS].map((domain) => ({
    domain,
    taxonomy: taxonomyOf(domain),
  }));

  it("reads Electronics' taxonomy", () => {
    const taxonomy = taxonomyOf("electronics")!;
    expect(taxonomy.length).toBeGreaterThanOrEqual(40);
    expect(taxonomy.filter(([, parent]) => parent === null)).toHaveLength(8);
  });

  it.each(departments.filter((d) => d.taxonomy !== null).map((d) => [d.domain, d.taxonomy!]))(
    "reads at least one category from %s's profile, so the check below is not vacuous",
    (_, taxonomy) => {
      expect(taxonomy.length).toBeGreaterThan(0);
      expect(taxonomy.some(([, parent]) => parent === null)).toBe(true);
    },
  );

  // Every department with any icon drawn, checked against its taxonomy.
  const rows = departments.flatMap(({ domain, taxonomy }) =>
    (taxonomy ?? []).map(([slug, parent]) => [`${domain}:${slug}`, parent] as const),
  );

  it.each(rows)("%s is drawn", (ref, parent) => {
    const glyph = categoryGlyph(ref);
    expect(glyph, `draw ${ref} in components/category-icons.tsx`).not.toBeNull();
    // Groups are objects, categories symbols: the two families must not swap.
    expect(glyph?.kind).toBe(parent === null ? "group" : "category");
  });

  it("draws no icon for a ref the taxonomy does not have", () => {
    // A mistyped or retired ref would otherwise sit in the registry unseen.
    const known = new Set<string>(rows.map(([ref]) => ref));
    expect(Object.keys(CATEGORY_ICONS).filter((ref) => !known.has(ref))).toEqual([]);
  });
});

describe("the registry is keyed by ref, and falls back cleanly", () => {
  it("keys every icon by domain:slug", () => {
    for (const ref of Object.keys(CATEGORY_ICONS)) expect(ref).toMatch(/^[a-z0-9-]+:[a-z0-9-]+$/);
  });

  it("never matches a bare slug, nor another department's same slug", () => {
    expect(categoryGlyph("measurement")).toBeNull();
    expect(categoryGlyph("electronics:measurement")).not.toBeNull();
    expect(categoryGlyph("tools:measurement")).not.toBe(categoryGlyph("electronics:measurement"));
    expect(categoryGlyph("welding:measurement")).toBeNull();
    expect(categoryGlyph("toString")).toBeNull();
  });

  it("knows which departments are drawn", () => {
    expect([...DEPARTMENTS_WITH_ICONS].sort()).toEqual(
      [
        "automotive",
        "chemicals",
        "cleaning",
        "electrical",
        "electronics",
        "garden",
        "machinery",
        "materials",
        "photography",
        "piping",
        "rigging",
        "safety",
        "seals-bearings",
        "security",
        "timber",
        "tools",
        "welding",
      ].sort(),
    );
    expect(hasCategoryIcons("electronics")).toBe(true);
    expect(hasCategoryIcons("seals-bearings")).toBe(true);
    expect(hasCategoryIcons("undrawn-dept")).toBe(false);
  });

  it("has a drawn set for every department with a profile", () => {
    // Every vertical is drawn now; a new one fails here until its set exists.
    const profiles = readdirSync(DOMAINS)
      .filter((f) => f.endsWith(".py") && !["__init__.py", "base.py"].includes(f))
      .map((f) => f.replace(/\.py$/, "").replace(/_/g, "-"));
    for (const domain of profiles) expect(hasCategoryIcons(domain), domain).toBe(true);
  });

  it("renders nothing for a category it has not drawn", () => {
    expect(renderToStaticMarkup(<CategoryIcon iconRef="electronics:not-drawn" />)).toBe("");
  });

  it("gives an undrawn group tile its department's icon", () => {
    expect(tileIcon("welding:not-drawn", "welding")).toBe(departmentIcon("welding"));
    expect(tileIcon("electronics:power", "electronics")).not.toBe(departmentIcon("electronics"));
    const Tile = tileIcon("electronics:power", "electronics");
    expect(renderToStaticMarkup(<Tile className="x" strokeWidth={1.25} />)).toContain(
      'stroke-width="1.5"',
    );
  });
});

/**
 * Icons that are deliberately one glyph, because they mean the same thing: the
 * catch-all "Other …" categories. Anything else drawn twice is a mistake.
 */
const SAME_GLYPH_ALLOWED: string[][] = [
  [
    "tools:hand-tools-other",
    "tools:power-tools-other",
    "tools:measurement-other",
    "tools:consumables-other",
    "machinery:general-pumps",
    "garden:garden-power-other",
  ],
];

describe("no two icons are the same drawing", () => {
  const byDrawing = new Map<string, string[]>();
  for (const [ref, glyph] of ENTRIES) {
    const drawing = renderToStaticMarkup(glyph.body);
    byDrawing.set(drawing, [...(byDrawing.get(drawing) ?? []), ref]);
  }
  const shared = [...byDrawing.values()].filter((refs) => refs.length > 1);

  it("repeats a drawing only where the allow-list says it is the same thing", () => {
    const allowed = SAME_GLYPH_ALLOWED.map((refs) => [...refs].sort().join());
    const found = shared.map((refs) => [...refs].sort().join());
    expect(found.sort()).toEqual(allowed.sort());
  });

  it("allows only refs that exist", () => {
    for (const ref of SAME_GLYPH_ALLOWED.flat()) expect(categoryGlyph(ref), ref).not.toBeNull();
  });
});

describe("S7 · department tile icons follow the style guide", () => {
  const domains = readdirSync(DOMAINS)
    .filter((f) => f.endsWith(".py") && !["__init__.py", "base.py"].includes(f))
    .map((f) => f.replace(/\.py$/, "").replace(/_/g, "-"));

  it("finds the departments", () => {
    expect(domains.length).toBeGreaterThanOrEqual(16);
  });

  it.each(domains)("%s has a drawn tile icon", (domain) => {
    const Icon = departmentIcon(domain);
    const html = renderToStaticMarkup(<Icon />);
    const svg = new DOMParser().parseFromString(html, "image/svg+xml").documentElement;
    expect(svg.getAttribute("data-department-icon"), `draw ${domain} in departments.tsx`).toBe(
      domain,
    );
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("fill")).toBe("none");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("stroke-width")).toBe("1.5");
    expect(svg.getAttribute("stroke-linecap")).toBe("round");
    expect(svg.getAttribute("stroke-linejoin")).toBe("round");
    const shapes = [...svg.querySelectorAll("*")];
    expect(shapes.length).toBeGreaterThan(0);
    for (const shape of shapes) {
      expect(["path", "rect", "circle", "line", "ellipse"]).toContain(shape.tagName);
      for (const { name, value } of [...shape.attributes]) {
        expect(ATTRIBUTES, `${domain}: <${shape.tagName} ${name}="${value}">`).toContain(name);
      }
    }
    // A tile is an object, so nothing reaches the margin.
    expect(outsideLiveArea(svg, [2, 22]), domain).toEqual([]);
  });
});
