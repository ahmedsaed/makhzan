/**
 * Draws the background pattern's tiles: line icons of the things makhzan lists,
 * scattered at seeded random positions, sizes and rotations.
 *
 *   public/pattern-wide.svg    tablets and desktops
 *   public/pattern-narrow.svg  phones: smaller icons, spaced further apart
 *
 * The tiles are masks, not pictures: they are drawn in plain black and the page
 * paints them in the `pattern` token through CSS `mask-image` (globals.css,
 * `.bg-pattern`), so the colour follows the theme and lives only in the tokens
 * (rule S1). One cached file per width, no DOM.
 *
 * The seed is fixed, so the output is the same on every run and the committed
 * files never churn. Change the seed, the icons or the spacing and run it again
 * from apps/web: `node scripts/pattern-tile.mjs`.
 *
 * Icons: fourteen from Lucide (ISC licence, already a dependency), the rest drawn
 * here on Lucide's 24-unit grid with the same round caps and joins. Every icon
 * gets the same stroke width.
 */
import { writeFile } from "node:fs/promises";
import { join } from "node:path";

import {
  Battery,
  Bolt,
  Cable,
  Cog,
  Cpu,
  Drill,
  Gauge,
  Hammer,
  Magnet,
  Microchip,
  Plug,
  Ruler,
  Spool,
  Wrench,
} from "lucide-react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const ROOT = join(import.meta.dirname, "..");
const SEED = 0x6d616b68; // "makh"
const STROKE = 1.5;

/** Lucide's drawing, without its own <svg> wrapper and attributes. */
function lucide(Icon) {
  const markup = renderToStaticMarkup(createElement(Icon));
  return markup.replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");
}

/** The rest, drawn for this pattern on a 24-unit grid. */
const CUSTOM = {
  resistor: `<path d="M2 12h4M18 12h4"/><rect x="6" y="9" width="12" height="6" rx="3"/><path d="M9.5 9v6M12.5 9v6M15 9v6"/>`,
  capacitor: `<rect x="7" y="3" width="10" height="13" rx="2"/><path d="M7 6.5h10M10 16v5M14 16v3"/>`,
  led: `<path d="M8 14V9a4 4 0 0 1 8 0v5M6.5 14h11M10 14v7M14 14v5"/>`,
  breadboard: `<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 12h18M7 8.5h0M10 8.5h0M13 8.5h0M16 8.5h0M7 15.5h0M10 15.5h0M13 15.5h0M16 15.5h0"/>`,
  servo: `<rect x="4" y="10" width="16" height="9" rx="1.5"/><path d="M2 12h2M20 12h2M9 8v2"/><rect x="5" y="5" width="9" height="3" rx="1.5"/>`,
  screwdriver: `<rect x="2" y="9" width="8" height="6" rx="2"/><path d="M10 11h2v2h-2M12 12h8M20 10.5v3"/>`,
  drillBit: `<path d="M3 12h7M10 10h9l2 2-2 2h-9zM12.5 10l2 4M16 10l2 4"/>`,
  caliper: `<rect x="2" y="4" width="20" height="4" rx="1"/><path d="M4 8v11l3-4V8"/><rect x="12" y="3" width="5" height="7" rx="1"/><path d="M12 10v9l3-4v-5"/>`,
  bearing: `<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="3.5"/><circle cx="12" cy="5.5" r="1.5"/><circle cx="17.6" cy="15.25" r="1.5"/><circle cx="6.4" cy="15.25" r="1.5"/><circle cx="17.6" cy="8.75" r="1.5"/><circle cx="6.4" cy="8.75" r="1.5"/><circle cx="12" cy="18.5" r="1.5"/>`,
  oRing: `<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="6"/>`,
  valve: `<path d="M3 9v8M21 9v8M5 9l7 4-7 4zM19 9l-7 4 7 4zM12 13V6M8 5h8"/>`,
  elbow: `<path d="M3 21v-9a9 9 0 0 1 9-9h9M9 21v-9a3 3 0 0 1 3-3h9M3 21h6M21 3v6"/>`,
  plank: `<rect x="2" y="7" width="20" height="10" rx="1"/><path d="M5 10.5c3-1.5 6 1.5 9 0s4-1 6 0M4 14c3 1 5-1 8 0"/><ellipse cx="16.5" cy="13.5" rx="1.5" ry="1"/>`,
  breaker: `<rect x="6" y="2" width="12" height="20" rx="2"/><rect x="10" y="7" width="4" height="8" rx="1"/><path d="M9 18.5h6"/>`,
  spring: `<path d="M12 2v2L7 6l10 3-10 3 10 3-10 3 5 2v2"/>`,
  screw: `<rect x="7" y="2" width="10" height="4" rx="1"/><path d="M10 6v14l2 2 2-2V6M10 9.5l4-1M10 12.5l4-1M10 15.5l4-1M10 18.5l4-1"/>`,
};

const ICONS = {
  ...Object.fromEntries(
    Object.entries({
      Battery,
      Bolt,
      Cable,
      Cog,
      Cpu,
      Drill,
      Gauge,
      Hammer,
      Magnet,
      Microchip,
      Plug,
      Ruler,
      Spool,
      Wrench,
    }).map(([name, Icon]) => [name, lucide(Icon)]),
  ),
  ...CUSTOM,
};

/** mulberry32: small, fast, and the same sequence everywhere. */
function random(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(list, rand) {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * Dart throwing on a torus: a point is kept only if it is at least `gap` from
 * every other, measured across the tile's edges too, so the seams look like the
 * middle. Icons are dealt from reshuffled decks, so neighbours rarely repeat.
 */
function scatter({ width, height, gap, size: [min, max] }, rand) {
  const placed = [];
  const names = Object.keys(ICONS);
  let deck = [];
  for (let attempt = 0; attempt < 20_000; attempt++) {
    const x = rand() * width;
    const y = rand() * height;
    const clear = placed.every((p) => {
      const dx = Math.min(Math.abs(p.x - x), width - Math.abs(p.x - x));
      const dy = Math.min(Math.abs(p.y - y), height - Math.abs(p.y - y));
      return dx * dx + dy * dy >= gap * gap;
    });
    if (!clear) continue;
    if (deck.length === 0) deck = shuffle(names, rand);
    placed.push({
      x,
      y,
      icon: deck.pop(),
      size: min + rand() * (max - min),
      angle: rand() * 360,
    });
  }
  return placed;
}

const round = (n) => Math.round(n * 10) / 10;

function tile(spec, rand) {
  const { width, height } = spec;
  const placed = scatter(spec, rand);
  const uses = [];
  for (const { x, y, icon, size, angle } of placed) {
    // An icon over an edge is drawn again on the far side, or the tile would
    // clip it in half where it repeats.
    const reach = size * 0.75;
    const xs = [x, ...(x < reach ? [x + width] : []), ...(x > width - reach ? [x - width] : [])];
    const ys = [y, ...(y < reach ? [y + height] : []), ...(y > height - reach ? [y - height] : [])];
    for (const cx of xs) {
      for (const cy of ys) {
        const s = round(size);
        uses.push(
          `<use href="#${icon}" x="${round(cx - size / 2)}" y="${round(cy - size / 2)}" width="${s}" height="${s}" transform="rotate(${Math.round(angle)} ${round(cx)} ${round(cy)})"/>`,
        );
      }
    }
  }
  const used = [...new Set(placed.map((p) => p.icon))].sort();
  const symbols = used.map(
    (name) => `<symbol id="${name}" viewBox="0 0 24 24">${ICONS[name]}</symbol>`,
  );
  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<defs>${symbols.join("")}</defs>`,
    `<g fill="none" stroke="black" stroke-width="${STROKE}" stroke-linecap="round" stroke-linejoin="round">`,
    ...uses,
    `</g></svg>`,
  ].join("\n");
  return { svg, count: placed.length, kinds: used.length };
}

const rand = random(SEED);
// Odd sizes, so the repeat does not line up with anything else on the page.
const TILES = {
  "pattern-wide.svg": { width: 1180, height: 740, gap: 92, size: [22, 30] },
  "pattern-narrow.svg": { width: 430, height: 620, gap: 76, size: [20, 26] },
};

for (const [name, spec] of Object.entries(TILES)) {
  const { svg, count, kinds } = tile(spec, rand);
  await writeFile(join(ROOT, "public", name), svg + "\n");
  console.log(`${name}: ${count} icons, ${kinds} kinds, ${svg.length} bytes`);
}
