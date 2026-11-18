/**
 * Builds the owner's contact sheet of every drawn icon. Not a test: it runs only
 * when GALLERY_OUT names a file, so the normal suite skips it.
 *
 *   GALLERY_OUT=../../ml/out/mockups/icons-all-departments.html \
 *     pnpm exec vitest run tests/icon-gallery.test.tsx
 */
import { writeFileSync } from "node:fs";

import { renderToStaticMarkup } from "react-dom/server";
import { describe, it } from "vitest";

import { CATEGORY_ICONS, CategoryIcon } from "@/components/category-icons";
import { DepartmentIcon } from "@/components/department-icon";

const OUT = process.env.GALLERY_OUT;

/** Departments in sheet order, with the ones drawn so far. */
const SECTIONS: [string, string][] = [
  ["electrical", "Electrical"],
  ["tools", "Tools"],
  ["seals-bearings", "Seals & Bearings"],
  ["machinery", "Machinery"],
  ["chemicals", "Chemicals"],
  ["welding", "Welding"],
  ["materials", "Materials"],
];

const TILES = [
  "electronics",
  "electrical",
  "tools",
  "seals-bearings",
  "automotive",
  "chemicals",
  "cleaning",
  "garden",
  "machinery",
  "materials",
  "piping",
  "rigging",
  "safety",
  "security",
  "timber",
  "welding",
  "photography",
];

/** Icons the artist is least sure of: said so on the sheet, with why. */
const WEAK: Record<string, string> = {
  "tools:pliers": "Two crossing lines; could pass for scissors or tongs.",
  "tools:precision-measure": "A beam and two jaws: reads as a ruler with legs.",
  "tools:tool-consumables": "A box with bars: reads as a battery or a barcode.",
  "tools:automotive-tools": "A wheel; says car, not car tools.",
  "tools:welding-tools": "A soldering iron only; welding gear has no clear small silhouette.",
  "tools:test-instruments": "A multimeter; close to the electronics one in spirit.",
  "tools:drills": "Chuck end-on; the pistol drill is the group's icon instead.",
  "tools:hand-tools": "A diagonal spanner; the group is bigger than one wrench.",
  "tools:wrenches": "Jaw round a nut: schematic, but unlike the group's spanner.",
  "tools:blades-discs": "A blade only; the cutting disc is the saw.",
  "electrical:disconnectors": "Differs from the breaker by one tick; small apart.",
  "electrical:circuit-breakers": "Standard breaker symbol; obscure to a layman.",
  "electrical:overload-relays": "Resistor-like box; the zigzag carries it.",
  "electrical:stabilizers": "A transformer symbol standing for stabilizers and PF correction.",
  "electrical:signal-conditioning": "A box with a wave: generic.",
  "electrical:capacitive-sensors": "Sensor beside a tank; the idea is level sensing.",
  "electrical:sensor-accessories": "A cable connector; brackets are not shown.",
  "electrical:process-switches": "Float only; pressure and flow are not shown.",
  "electrical:control-signalling": "Mushroom button; the group also holds lamps.",
  "seals-bearings:gland-packing": "A stack of rings: abstract.",
  "seals-bearings:graphite-mica": "Offset sheets: says layers, not graphite.",
  "seals-bearings:sealing-tape": "A roll with a tail; close to the o-ring.",
  "seals-bearings:machine-spares": "A hex nut standing for any spare.",
  "seals-bearings:auto-lubricators": "A tall cartridge: generic.",
  "seals-bearings:mechanical-seals": "Spring and two faces: right to an engineer, odd to others.",
  "seals-bearings:sight-glasses": "A window with a level line; reads as a gauge more than glass.",
  "seals-bearings:gaskets": "A flat square gasket; the real ones come in every shape.",
  "seals-bearings:o-rings": "Two circles: near the gasket and the bearing.",
  "machinery:machinery-accessories": "A drawer chest; says storage more than accessories.",
  "machinery:pump-controllers": "A control box with a dial; generic.",
  "machinery:machine-tools": "A lathe bed and headstock; reads as abstract blocks.",
  "machinery:concrete-mixers": "A barrel on legs; a drum mixer is hard to draw small.",
  "machinery:concrete-vibrators": "A poker head on a hose; the waves carry it.",
  "machinery:concrete-saws": "A blade over a slab; close to the saws icon in tools.",
  "machinery:concrete-tools": "A trowel; the category also holds floats and screeds.",
  "machinery:hydraulic-components": "A hydraulic pump symbol; obscure outside the trade.",
  "machinery:machine-connectors": "A fitting between two pipe stubs; close to a fuse.",
  "chemicals:adhesive-tapes": "A roll on its strip; close to the filament spool in electronics.",
  "chemicals:paints": "A brush; the group's bucket carries the idea better.",
  "chemicals:rust-removers": "A threaded bolt with flakes; says bolt more than remover.",
  "chemicals:foams": "A can beside a cloud of foam.",
  "chemicals:sealants": "Two blocks with a bead between; schematic.",
  "chemicals:industrial-adhesives": "Two bonded plates with dots for glue.",
  "chemicals:general-chemicals": "A beaker; stands for any chemical.",
  "welding:welding-accessories": "A wire brush; the group holds clamps, magnets and more.",
  "welding:welding-machines": "An arc on a plate rather than a machine.",
  "welding:cutting-machines": "A torch over a cut plate; close to cutting torches.",
  "welding:cutting-torches": "Handle, tube and a right-angle head; hard to read small.",
  "welding:electrodes": "A coated rod; close to a pencil.",
  "welding:earth-clamps": "Two jaws; could be a crocodile or a pair of pliers.",
  "welding:flashback-arrestors": "A check-valve symbol in a body; close to piping's check valves.",
  "welding:rod-heaters": "An oven with rods; says box.",
  "welding:torch-heaters": "A flame beside a gas bottle; close to the instant-adhesive drop.",
  "welding:torch-lighters": "A lighter with a flame; the real one is a flint striker.",
  "materials:rubber-sheet": "A slab in isometric; close to the group's stack of sheets.",
  "materials:anti-vibration-pads": "A foot on a spring pad; schematic.",
  "materials:membranes": "Rain over a layer; says waterproofing, not membrane.",
  "materials:polyester-resins": "A weave grid for fibreglass; reads as a grid or a table.",
  "materials:safety-flooring": "A plate with ridges; reads as a tile.",
  "materials:insulation": "A wall with wavy fill; the loops say insulation to the trade only.",
  "materials:metal-stock": "Round bars end-on; says pipes or logs.",
  "materials:decorative-aggregates": "Three mounds for stone and sand.",
};

function cell(ref: string, label: string): string {
  const weak = WEAK[ref];
  const svg = renderToStaticMarkup(<CategoryIcon iconRef={ref} />);
  return `<figure class="cell${weak ? " weak" : ""}">
    <div class="sizes"><span class="s24">${svg}</span><span class="s48">${svg}</span></div>
    <figcaption><b>${label}</b><code>${ref}</code>${
      weak ? `<em>weak: ${weak}</em>` : ""
    }</figcaption></figure>`;
}

describe.skipIf(!OUT)("icon gallery", () => {
  it("writes the contact sheet", () => {
    const tiles = TILES.map((d) => {
      const svg = renderToStaticMarkup(<DepartmentIcon domain={d} />);
      return `<figure class="cell"><div class="sizes"><span class="s24">${svg}</span><span class="s48">${svg}</span></div><figcaption><b>${d}</b></figcaption></figure>`;
    }).join("");
    const sections = SECTIONS.map(([domain, name]) => {
      const entries = Object.entries(CATEGORY_ICONS).filter(([ref]) =>
        ref.startsWith(`${domain}:`),
      );
      const groups = entries.filter(([, g]) => g.kind === "group");
      const cats = entries.filter(([, g]) => g.kind === "category");
      const weak = entries.filter(([ref]) => WEAK[ref]).length;
      return `<section><h2>${name} <small>${groups.length} groups, ${cats.length} categories${
        weak ? `, ${weak} marked weak` : ""
      }</small></h2>
      <h3>Groups (objects)</h3><div class="grid">${groups.map(([r, g]) => cell(r, g.label)).join("")}</div>
      <h3>Categories (symbols)</h3><div class="grid">${cats.map(([r, g]) => cell(r, g.label)).join("")}</div></section>`;
    }).join("\n");
    const html = `<!doctype html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Category icons, all departments</title>
<style>
:root{--ground:#f6f6f3;--surface:#fff;--ink:#15171c;--ink-2:#4a4f5a;--ink-3:#6b7080;--line:#e3e3de;--warn:#9a3412;color-scheme:light}
:root[data-theme=dark]{--ground:#121316;--surface:#1b1d21;--ink:#ececea;--ink-2:#b5b8bf;--ink-3:#9095a0;--line:#2c2f35;--warn:#fdba8c;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
.page{max-width:1200px;margin:0 auto;padding:20px 16px 64px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
h1{font-size:24px;margin:0 0 4px}p{color:var(--ink-2);margin:0;max-width:70ch}
button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:8px 14px;min-height:44px}
section{margin-top:36px}h2{font-size:21px;margin:0}h2 small{font-size:13px;color:var(--ink-3);font-weight:400;margin-left:8px}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-3);margin:18px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
.cell{margin:0;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:8px;min-width:0}
.cell.weak{border-color:var(--warn)}
.sizes{display:flex;align-items:flex-end;gap:14px;color:var(--ink-2)}
.s24 svg{width:24px;height:24px;display:block}.s48 svg{width:48px;height:48px;display:block}
figcaption{display:flex;flex-direction:column;gap:2px;font-size:12.5px;line-height:1.3}
figcaption code{font-size:11px;color:var(--ink-3);overflow-wrap:anywhere}
figcaption em{font-style:normal;color:var(--warn);font-size:11.5px}
</style></head><body><div class="page">
<header><div><h1>Category icons, all departments</h1>
<p>Checkpoint sheet: electrical, tools, seals &amp; bearings, and every department tile. Each icon at 24 px and 48 px. Orange-bordered cells are the ones I think are weak, with why.</p></div>
<button id="t" type="button">Light</button></header>
<section><h2>Department tiles <small>17</small></h2><div class="grid">${tiles}</div></section>
${sections}
</div><script>
var r=document.documentElement,b=document.getElementById('t');
b.onclick=function(){var d=r.getAttribute('data-theme')==='dark';r.setAttribute('data-theme',d?'light':'dark');b.textContent=d?'Dark':'Light'};
</script></body></html>`;
    writeFileSync(OUT!, html);
  });
});
