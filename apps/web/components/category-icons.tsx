import type { ComponentType } from "react";

import { ELECTRICAL_ICONS } from "@/components/category-icon-sets/electrical";
import type { Glyph, GlyphKind } from "@/components/category-icon-sets/types";
import { departmentIcon } from "@/components/department-icon";

export type { Glyph, GlyphKind };

/**
 * makhzan's own icon set for departments' groups and categories (docs/DESIGN.md,
 * "Category icons"; the owner approved option 3 of the icon pilot, November 2026).
 *
 * The style, which tests/category-icons.test.tsx holds every icon to:
 * - a 24 × 24 grid, drawn inside the 20 × 20 live area a 2-unit margin leaves;
 *   only a schematic symbol's leads may run on to the edge, as a wire would;
 * - one stroke, 1.5 units, with round caps and joins; a dot is a zero-length
 *   segment (`h0`), so it is exactly as heavy as a line;
 * - no fills, and `currentColor`, so an icon takes the colour of its text;
 * - strokes at least 2 units apart, so two lines stay two lines at 18px;
 * - a group is an object you would hold (a board, a motor, a printer), a
 *   category its schematic symbol where electronics has one everyone reads
 *   (resistor, capacitor, diode), else a package or part (a DIP chip, an LED).
 *   The two families then look different at a glance.
 *
 * Keyed by category ref, `domain:slug`, never a bare slug: slugs repeat across
 * departments ("tools:measurement" is not "electronics:measurement"). A group
 * is a top-level category, so its key is its ref too.
 *
 * Shown in the department pages' browse tree (components/browse-tree.tsx).
 * A department either has a drawn set or it does not. Without one, its
 * categories show plain, with no icon at all (a column of one repeated
 * stand-in says nothing), and its groups keep the department's line icon
 * (components/department-icon.tsx) until its set is drawn. A category added
 * to a drawn department later (a new electronics leaf) shows plain until its
 * icon is added here; tests/category-icons.test.tsx fails until then, so it
 * cannot be forgotten.
 *
 * Icons may run ahead of the taxonomy: electronics:cameras, electronics:kits
 * and the photography department are drawn for feat/taxonomy-gaps before it
 * merges. A ref nothing lists yet is simply never looked up.
 */

export const CATEGORY_ICONS: Readonly<Record<string, Glyph>> = {
  ...ELECTRICAL_ICONS,
  // Groups: objects you would hold.
  "electronics:components": {
    label: "Components",
    kind: "group",
    body: (
      <>
        <path d="M6.5 5.5v10.5a5.5 2 0 0 0 11 0V5.5" />
        <ellipse cx="12" cy="5.5" rx="5.5" ry="2" />
        <path d="M14.5 9v5.5M9.5 18v3.5M14.5 18v2" />
      </>
    ),
  },
  "electronics:boards-modules": {
    label: "Boards & Modules",
    kind: "group",
    body: (
      <>
        <path d="M7 7V4.5A1.5 1.5 0 0 1 8.5 3h11A1.5 1.5 0 0 1 21 4.5v10a1.5 1.5 0 0 1-1.5 1.5H17" />
        <rect x="3" y="7" width="14" height="14" rx="1.5" />
        <rect x="7" y="11" width="6" height="6" rx="0.75" />
      </>
    ),
  },
  "electronics:power": {
    label: "Power",
    kind: "group",
    body: (
      <>
        <rect x="2.5" y="7" width="17" height="10" rx="2" />
        <path d="M21.5 10.5v3" />
        <path d="M12.5 9.25 9.75 12.5h4.5l-2.75 3.25" />
      </>
    ),
  },
  "electronics:electromechanical": {
    label: "Motors & Actuators",
    kind: "group",
    body: (
      <>
        <rect x="2.5" y="6.5" width="13" height="11" rx="2.5" />
        <path d="M6.5 6.5v11" />
        <path d="M15.5 9h2a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1h-2M18.5 12h3.5" />
      </>
    ),
  },
  "electronics:printing-cnc": {
    label: "3D Printing & CNC",
    kind: "group",
    body: (
      <>
        <path d="M4.5 21V3.5h15V21M3 21h18M4.5 8h15" />
        <rect x="9.5" y="6" width="5" height="4" rx="0.75" />
        <path d="M11 10l1 1.75 1-1.75" />
        <path d="M7 18h10" />
        <rect x="9.25" y="14.5" width="5.5" height="3.5" rx="0.5" />
      </>
    ),
  },
  "electronics:tools": {
    label: "Tools & Equipment",
    kind: "group",
    body: (
      <>
        <path d="M6.31 4.54L8.64 6.87L6.87 8.64L4.54 6.31A4 4 0 0 0 9.67 11.79L16.6 18.72A1.5 1.5 0 0 0 18.72 16.6L11.79 9.67A4 4 0 0 0 6.31 4.54Z" />
        <path d="M12 9.17L16.6 4.58A2 2 0 0 1 19.42 7.4L14.83 12Z" />
        <path d="M13.41 10.59L6.7 17.3" />
      </>
    ),
  },
  "electronics:prototyping": {
    label: "Prototyping",
    kind: "group",
    body: (
      <>
        <rect x="2.5" y="4.5" width="19" height="15" rx="2" />
        <path d="M2.5 12h19" />
        <path d="M6 8h0M9 8h0M12 8h0M15 8h0M18 8h0M6 16h0M9 16h0M12 16h0M15 16h0M18 16h0" />
      </>
    ),
  },
  "electronics:other": {
    label: "Accessories & Other",
    kind: "group",
    body: (
      <>
        <path d="M12 3 20.5 7.25v9.5L12 21l-8.5-4.25v-9.5z" />
        <path d="m3.5 7.25 8.5 4.25 8.5-4.25M12 11.5V21" />
        <path d="m7.75 5.1 8.5 4.3" />
      </>
    ),
  },
  // Categories: schematic symbols, or a package or object where no symbol is read.
  "electronics:resistors": {
    label: "Resistors",
    kind: "category",
    body: (
      <>
        <path d="M2 12h2.5l1.25-3 2.5 6 2.5-6 2.5 6 2.5-6 2.5 6 1.25-3H22" />
      </>
    ),
  },
  "electronics:potentiometers": {
    label: "Potentiometers",
    kind: "category",
    body: (
      <>
        <path d="M2 14h2.5L6 11.5l3 5 3-5 3 5 3-5 1.5 2.5H22" />
        <path d="M12 3v6.5M9.75 7.5 12 9.75l2.25-2.25" />
      </>
    ),
  },
  "electronics:capacitors": {
    label: "Capacitors",
    kind: "category",
    body: (
      <>
        <path d="M2 12h8.5M13.5 12H22M10.5 6.5v11M13.5 6.5v11" />
      </>
    ),
  },
  "electronics:inductors": {
    label: "Inductors & Transformers",
    kind: "category",
    body: (
      <>
        <path d="M2 14h2.5a2.5 2.5 0 0 1 5 0 2.5 2.5 0 0 1 5 0 2.5 2.5 0 0 1 5 0H22" />
      </>
    ),
  },
  "electronics:transistors": {
    label: "Transistors & MOSFETs",
    kind: "category",
    body: (
      <>
        <path d="M2 12H7.5M7.5 7v10M10.5 5.5v13" />
        <path d="M10.5 7.5H16V2M10.5 16.5H16V22" />
        <path d="m13.5 14.75 2.5 1.75-2.5 1.75" />
      </>
    ),
  },
  "electronics:diodes": {
    label: "Diodes",
    kind: "category",
    body: (
      <>
        <path d="M2 12h6M16 12h6M8 7v10l8-5zM16 7v10" />
      </>
    ),
  },
  "electronics:ics": {
    label: "Integrated Circuits",
    kind: "category",
    body: (
      <>
        <rect x="6.5" y="3.5" width="11" height="17" rx="1.5" />
        <path d="M10.5 3.5a1.5 1.5 0 0 0 3 0" />
        <path d="M3 8h3.5M3 12h3.5M3 16h3.5M17.5 8H21M17.5 12H21M17.5 16H21" />
      </>
    ),
  },
  "electronics:regulators": {
    label: "Voltage Regulators",
    kind: "category",
    body: (
      <>
        <rect x="7.5" y="5.5" width="9" height="8" rx="1" />
        <path d="M2 9.5q1.25-2.5 2.75 0t2.75 0M16.5 9.5H22M12 13.5V18M8.5 18h7M10.25 21h3.5" />
      </>
    ),
  },
  "electronics:leds": {
    label: "LEDs & Optoelectronics",
    kind: "category",
    body: (
      <>
        <path d="M6 15V9.5a4 4 0 0 1 8 0V15" />
        <path d="M4 15h12M8 15v6.5M12 15v5" />
        <path d="M17.5 7 20 4.5M18 11h3" />
      </>
    ),
  },
  "electronics:crystals": {
    label: "Crystals & Oscillators",
    kind: "category",
    body: (
      <>
        <path d="M2 12h5M17 12h5M7 7.5v9M17 7.5v9" />
        <rect x="9.5" y="6.5" width="5" height="11" rx="0.75" />
      </>
    ),
  },
  "electronics:connectors": {
    label: "Connectors & Sockets",
    kind: "category",
    body: (
      <>
        <path d="M2 12h3" />
        <rect x="5" y="7.5" width="6" height="9" rx="1" />
        <path d="M11 10h3M11 14h3" />
        <path d="M22 12h-3M19 7.5h-3.5a1 1 0 0 0-1 1v7a1 1 0 0 0 1 1H19z" />
      </>
    ),
  },
  "electronics:switches-relays": {
    label: "Switches & Relays",
    kind: "category",
    body: (
      <>
        <path d="M2 14.5h4.5M18.5 14.5H22" />
        <circle cx="7.75" cy="14.5" r="1.25" />
        <circle cx="17.25" cy="14.5" r="1.25" />
        <path d="M8.85 13.85 16.5 8" />
      </>
    ),
  },
  "electronics:fuses": {
    label: "Fuses & Protection",
    kind: "category",
    body: (
      <>
        <rect x="5" y="8.5" width="14" height="7" rx="1.5" />
        <path d="M2 12h20" />
      </>
    ),
  },
  "electronics:audio": {
    label: "Audio",
    kind: "category",
    body: (
      <>
        <path d="M3 9.5h3.5L11.5 5v14l-5-4.5H3z" />
        <path d="M15 9.5a3.5 3.5 0 0 1 0 5M17.5 7a7 7 0 0 1 0 10" />
      </>
    ),
  },
  "electronics:dev-boards": {
    label: "Microcontrollers & Dev Boards",
    kind: "category",
    body: (
      <>
        <rect x="5.5" y="5.5" width="16" height="13" rx="1.5" />
        <path d="M2 9.5h5v5H2" />
        <path d="M10 8h0M12.5 8h0M15 8h0M17.5 8h0M10 16h0M12.5 16h0M15 16h0M17.5 16h0" />
      </>
    ),
  },
  "electronics:sensors": {
    label: "Sensors",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="6.5" width="19" height="11" rx="1.5" />
        <circle cx="7.5" cy="12" r="3" />
        <circle cx="16.5" cy="12" r="3" />
      </>
    ),
  },
  "electronics:wireless": {
    label: "Communication & Wireless",
    kind: "category",
    body: (
      <>
        <path d="M12 11v10.5M9 21.5h6" />
        <path d="M12 9h0" />
        <path d="M8.8 12.2a4.5 4.5 0 0 1 0-6.4M15.2 5.8a4.5 4.5 0 0 1 0 6.4M6 15a8.5 8.5 0 0 1 0-12M18 3a8.5 8.5 0 0 1 0 12" />
      </>
    ),
  },
  "electronics:displays": {
    label: "Displays",
    kind: "category",
    body: (
      <>
        <path d="M9 3.5h6M9 12h6M9 20.5h6M7.5 5v5.5M16.5 5v5.5M7.5 13.5V19M16.5 13.5V19M20 20.5h0" />
      </>
    ),
  },
  "electronics:modules": {
    label: "Modules",
    kind: "category",
    body: (
      <>
        <rect x="4" y="3" width="16" height="12.5" rx="1.5" />
        <rect x="9" y="7" width="6" height="4.5" rx="0.5" />
        <path d="M7.5 15.5v5M10.5 15.5v5M13.5 15.5v5M16.5 15.5v5" />
      </>
    ),
  },
  "electronics:cameras": {
    label: "Cameras & Imaging",
    kind: "category",
    body: (
      <>
        <rect x="4" y="3" width="16" height="12" rx="1.5" />
        <circle cx="12" cy="9" r="3.5" />
        <path d="M10.5 8.25a1.75 1.75 0 0 1 1.5-1" />
        <path d="M7.5 15v6.5h9V15M10.5 18h3" />
      </>
    ),
  },
  "electronics:power-supplies": {
    label: "Power Supplies & Converters",
    kind: "category",
    body: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <path d="M3.5 20.5l17-17" />
        <path d="M5.5 9q1.25-2.5 2.5 0t2.5 0M13.5 15h5M13.5 17.5h1M17.5 17.5h1" />
      </>
    ),
  },
  "electronics:batteries": {
    label: "Batteries & Chargers",
    kind: "category",
    body: (
      <>
        <path d="M2 12h6.25M15.75 12H22M8.25 7v10M10.75 9.5v5M13.25 7v10M15.75 9.5v5" />
      </>
    ),
  },
  "electronics:solar": {
    label: "Solar",
    kind: "category",
    body: (
      <>
        <path d="M5 3.5h14l2 11H3z" />
        <path d="M4 9h16M10 3.5l-.75 11M14 3.5l.75 11M12 14.5v5M8 20.5h8" />
      </>
    ),
  },
  "electronics:fans-cooling": {
    label: "Fans & Cooling",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="2.5" width="19" height="19" rx="3" />
        <circle cx="12" cy="12" r="2" />
        <path d="M12 10Q14.5 7 10.5 5Q8.5 8 10.27 11" />
        <path d="M13.73 13Q15.08 16.67 18.81 14.2Q17.21 10.97 13.73 11" />
        <path d="M10.27 13Q6.42 12.33 6.69 16.8Q10.29 17.03 12 14" />
      </>
    ),
  },
  "electronics:motors": {
    label: "Motors",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 2v2M12 20v2M8.5 15.5v-7l3.5 4.5 3.5-4.5v7" />
      </>
    ),
  },
  "electronics:servos": {
    label: "Servos & Actuators",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="10" width="11" height="6" rx="1.5" />
        <rect x="4.5" y="4.5" width="7" height="5.5" rx="1" />
        <path d="M13.5 13h4.25" />
        <circle cx="19.5" cy="13" r="1.75" />
        <path d="M5 19.5h6" />
      </>
    ),
  },
  "electronics:printers-3d": {
    label: "3D Printers",
    kind: "category",
    body: (
      <>
        <path d="M9 2.5h6v3.5l-2 2.5h-2l-2-2.5z" />
        <path d="M12 8.5v2" />
        <path d="M4 21.5h16M6 18.5h12M8 15.5h8M10 12.5h4" />
      </>
    ),
  },
  "electronics:filament": {
    label: "Filament & Resin",
    kind: "category",
    body: (
      <>
        <circle cx="10" cy="12" r="7.5" />
        <circle cx="10" cy="12" r="2.5" />
        <path d="M10 4.5h7.5a2.5 2.5 0 0 1 2.5 2.5v14.5" />
      </>
    ),
  },
  "electronics:printer-parts": {
    label: "Printer & CNC Parts",
    kind: "category",
    body: (
      <>
        <path d="M2.5 15h19M2.5 19h19" />
        <rect x="7" y="8" width="10" height="7" rx="1" />
        <path d="M9.5 11.5h0M14.5 11.5h0" />
      </>
    ),
  },
  "electronics:mechanical": {
    label: "Mechanical Parts",
    kind: "category",
    body: (
      <>
        <path d="M12.66 5.28L14.61 3.39L16.24 4.06L16.28 6.78L17.22 7.72L19.94 7.76L20.61 9.39L18.72 11.34L18.72 12.66L20.61 14.61L19.94 16.24L17.22 16.28L16.28 17.22L16.24 19.94L14.61 20.61L12.66 18.72L11.34 18.72L9.39 20.61L7.76 19.94L7.72 17.22L6.78 16.28L4.06 16.24L3.39 14.61L5.28 12.66L5.28 11.34L3.39 9.39L4.06 7.76L6.78 7.72L7.72 6.78L7.76 4.06L9.39 3.39L11.34 5.28Z" />
        <circle cx="12" cy="12" r="2.75" />
      </>
    ),
  },
  "electronics:soldering": {
    label: "Soldering",
    kind: "category",
    body: (
      <>
        <path d="M18.36 8.46L14.83 12L12 9.17L15.54 5.64A2 2 0 0 1 18.36 8.46Z" />
        <path d="M14.3 11.47L11.82 13.94L10.06 12.18L12.53 9.7" />
        <path d="M10.94 13.06L7.76 16.24M8.46 16.95L5.64 18.36L7.05 15.54Z" />
        <path d="M16.95 7.05c1 1 2.5 1.25 3 0.25s0.75 -1.25 2 -1.25" />
      </>
    ),
  },
  "electronics:hand-tools": {
    label: "Hand & Repair Tools",
    kind: "category",
    body: (
      <>
        <path d="M12 8.46L17.48 2.98A2.5 2.5 0 0 1 21.02 6.52L15.54 12Z" />
        <path d="M13.94 6.52L17.48 10.06M15.71 4.75L19.25 8.29" />
        <path d="M13.06 9.53L11.65 10.94L13.06 12.35L14.47 10.94" />
        <path d="M12.35 11.65L4.93 19.07M4.15 18.29L5.71 19.85" />
      </>
    ),
  },
  "electronics:measurement": {
    label: "Measurement & Test",
    kind: "category",
    body: (
      <>
        <rect x="6" y="2.5" width="12" height="13" rx="1.5" />
        <rect x="8.5" y="5" width="7" height="3" rx="0.5" />
        <circle cx="12" cy="11.5" r="1.75" />
        <path d="M9.5 15.5c0 3-4.5 2.5-6 6M14.5 15.5c0 3 4.5 2.5 6 6" />
      </>
    ),
  },
  "electronics:prototyping-supplies": {
    label: "Breadboards & Wires",
    kind: "category",
    body: (
      <>
        <rect x="3" y="15" width="4" height="5" rx=".5" />
        <path d="M5 20v2" />
        <rect x="17" y="4" width="4" height="5" rx=".5" />
        <path d="M19 4V2" />
        <path d="M5 15c0-6 14-0.5 14-6" />
      </>
    ),
  },
  "electronics:kits": {
    label: "Educational & Robot Kits",
    kind: "category",
    body: (
      <>
        <rect x="5" y="8" width="14" height="11" rx="2" />
        <path d="M12 8V5.5M12 3.25h0" />
        <path d="M9.5 12.5h0M14.5 12.5h0M10 15.5h4M3 11.5v4M21 11.5v4" />
      </>
    ),
  },
  "electronics:accessories": {
    label: "Accessories",
    kind: "category",
    body: (
      <>
        <rect x="10.5" y="8.5" width="7" height="7" rx="1" />
        <path d="M17.5 10h4v4h-4" />
        <path d="M10.5 12H8.5c-2.5 0-2.5 5.5-5 5.5H2.5" />
      </>
    ),
  },
  // Photography (feat/taxonomy-gaps): drawn ahead of the taxonomy reaching main.
  // No schematic symbols here, so its categories are drawn as the things themselves.
  "photography:lighting": {
    label: "Lighting",
    kind: "group",
    body: (
      <>
        <path d="M9.5 18h5M10 21h4" />
        <path d="M9.5 18c0-2-2.5-3-2.5-6a5 5 0 0 1 10 0c0 3-2.5 4-2.5 6" />
        <path d="M12 2.5v1M4.5 6l.75.75M19.5 6l-.75.75M2.5 12h1M20.5 12h1" />
      </>
    ),
  },
  "photography:camera-gear": {
    label: "Camera Gear",
    kind: "group",
    body: (
      <>
        <path d="M4.5 7h3l1.5-2.5h6L16.5 7h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
        <circle cx="12" cy="13" r="3.5" />
        <path d="M18 10h0" />
      </>
    ),
  },
  "photography:photo-lights": {
    label: "Photo & Video Lights",
    kind: "category",
    body: (
      <>
        <rect x="4" y="3" width="16" height="11" rx="1" />
        <rect x="7.5" y="6" width="9" height="5" rx="0.5" />
        <path d="M12 14v4M12 18l-3.5 3.5M12 18l3.5 3.5" />
      </>
    ),
  },
  "photography:tripods": {
    label: "Tripods & Stands",
    kind: "category",
    body: (
      <>
        <rect x="8.5" y="2.5" width="7" height="3" rx="0.75" />
        <path d="M12 5.5V10M12 10 5 21.5M12 10l7 11.5M12 10v11.5" />
      </>
    ),
  },
  "photography:camera-bags": {
    label: "Camera Bags",
    kind: "category",
    body: (
      <>
        <rect x="3" y="8" width="18" height="12.5" rx="2" />
        <path d="M8.5 8V6a1.5 1.5 0 0 1 1.5-1.5h4A1.5 1.5 0 0 1 15.5 6v2" />
        <path d="M3 12.5h18M10.5 12.5v2.5h3v-2.5" />
      </>
    ),
  },
  "photography:camera-accessories": {
    label: "Camera Accessories",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="4" />
        <path d="M8.5 8.5a5 5 0 0 1 2-1.25" />
      </>
    ),
  },
};

/** Departments whose groups and categories are drawn. */
export const DEPARTMENTS_WITH_ICONS: ReadonlySet<string> = new Set(
  Object.keys(CATEGORY_ICONS).map((ref) => ref.slice(0, ref.indexOf(":"))),
);

/** Whether a department's categories carry icons. */
export function hasCategoryIcons(domain: string): boolean {
  return DEPARTMENTS_WITH_ICONS.has(domain);
}

/** The drawn icon for a category or group ref, or null. A bare slug never matches. */
export function categoryGlyph(ref: string): Glyph | null {
  return Object.hasOwn(CATEGORY_ICONS, ref) ? CATEGORY_ICONS[ref] : null;
}

/**
 * A category's icon as an inline `<svg>`, or nothing when it is not drawn.
 * Decorative: the name beside it says the same, so it is hidden from
 * assistive technology.
 */
export function CategoryIcon({ iconRef, className }: { iconRef: string; className?: string }) {
  const glyph = categoryGlyph(iconRef);
  if (!glyph) return null;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      data-icon={iconRef}
      className={className}
    >
      {glyph.body}
    </svg>
  );
}

/** A group's icon: a lucide icon, or one of these. */
export type TileIcon = ComponentType<{ className?: string; strokeWidth?: number }>;

const TILE_ICONS = new Map<string, TileIcon>(
  Object.keys(CATEGORY_ICONS).map((ref) => {
    // The set's own stroke weight stands: a caller's `strokeWidth` is for lucide.
    const Drawn: TileIcon = ({ className }) => <CategoryIcon iconRef={ref} className={className} />;
    Drawn.displayName = `CategoryIcon(${ref})`;
    return [ref, Drawn];
  }),
);

/**
 * A group's icon in the browse tree: the drawn one, else the department's line
 * icon, so a group row never goes without one.
 */
export function tileIcon(ref: string, domain: string): TileIcon {
  return TILE_ICONS.get(ref) ?? departmentIcon(domain);
}
