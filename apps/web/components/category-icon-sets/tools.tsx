import { OTHER_BODY } from "./shared";
import type { Glyph } from "./types";

/** Tools: hand, power, measuring and air tools. Objects for groups, a recognisable part for each category. */
export const TOOLS_ICONS: Record<string, Glyph> = {
  // Groups
  "tools:hand-tools": {
    label: "Hand Tools",
    kind: "group",
    body: (
      <path d="M9.17 11.29L5.64 12L3.16 9.53L3.16 7.4L4.22 6.34L7.4 9.53L9.53 7.4L6.34 4.22L7.4 3.16L9.53 3.16L12 5.64L11.29 9.17L16.6 14.47L18.72 14.47L19.78 15.54L19.78 17.66L17.66 19.78L15.54 19.78L14.47 18.72L14.47 16.6Z" />
    ),
  },
  "tools:power-tools": {
    label: "Power Tools",
    kind: "group",
    body: (
      <>
        <rect x="3" y="5" width="13" height="6.5" rx="2" />
        <rect x="16" y="6.5" width="3" height="3.5" rx="0.5" />
        <path d="M19 8.25h2.5" />
        <path d="M7 11.5 6 21h5.25l1.25-9.5" />
      </>
    ),
  },
  "tools:measurement": {
    label: "Measurement & Layout",
    kind: "group",
    body: (
      <>
        <rect x="3.5" y="5.5" width="14" height="13.5" rx="3.5" />
        <circle cx="10.5" cy="12.25" r="3" />
        <path d="M17.5 16.5H22V12.5" />
      </>
    ),
  },
  "tools:tool-consumables": {
    label: "Accessories & Consumables",
    kind: "group",
    body: (
      <>
        <rect x="3" y="5.5" width="18" height="13" rx="2" />
        <path d="M7.5 9v6M12 9v6M16.5 9v6" />
      </>
    ),
  },
  "tools:pneumatic": {
    label: "Pneumatic & Air",
    kind: "group",
    body: (
      <>
        <rect x="3" y="8" width="13" height="8" rx="1" />
        <path d="M16 12h5.5M10 8v8M6 8V5M13 16v3" />
      </>
    ),
  },
  // Hand tools
  "tools:wrenches": {
    label: "Wrenches & Spanners",
    kind: "category",
    body: (
      <>
        <path d="M21 6.5H11a5.5 5.5 0 0 0 0 11h10" />
        <path d="M11 9l2.6 1.5v3L11 15l-2.6-1.5v-3z" />
      </>
    ),
  },
  "tools:sockets-drivers": {
    label: "Sockets & Drivers",
    kind: "category",
    body: (
      <>
        <path d="M8 3h8v5h2.5v13h-13V8H8z" />
        <path d="M5.5 14h13" />
        <path d="M10 17.5h4" />
      </>
    ),
  },
  "tools:pliers": {
    label: "Pliers & Grips",
    kind: "category",
    body: (
      <>
        <path d="M8 21.5l6.5-13 -1.7-5" />
        <path d="M16 21.5l-6.5-13 1.7-5" />
        <path d="M12 13.5h0" />
      </>
    ),
  },
  "tools:screwdrivers": {
    label: "Screwdrivers & Hex Keys",
    kind: "category",
    body: (
      <>
        <rect x="8.5" y="12" width="7" height="9.5" rx="3" />
        <path d="M12 12V6" />
        <path d="M10.5 2.5h3L12 6z" />
      </>
    ),
  },
  "tools:hammers": {
    label: "Hammers & Striking",
    kind: "category",
    body: (
      <>
        <rect x="4" y="3.5" width="16" height="6" rx="1.5" />
        <path d="M7.5 3.5v6M16.5 3.5v6" />
        <rect x="10" y="9.5" width="4" height="12" rx="1" />
      </>
    ),
  },
  "tools:cutting-hand": {
    label: "Hand Cutting Tools",
    kind: "category",
    body: (
      <>
        <circle cx="7" cy="18.5" r="2.5" />
        <circle cx="17" cy="18.5" r="2.5" />
        <path d="M8.2 16.3 17 3.5M15.8 16.3 7 3.5" />
      </>
    ),
  },
  "tools:clamps-vises": {
    label: "Clamps & Vises",
    kind: "category",
    body: (
      <>
        <path d="M19 2.5H8.5A5 5 0 0 0 3.5 7.5v6a5 5 0 0 0 5 5H19" />
        <path d="M14 18.5V8M11.5 8h5M10.5 21.5h7" />
      </>
    ),
  },
  "tools:painting-tools": {
    label: "Painting & Surface Tools",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="3.5" width="15" height="6" rx="2" />
        <path d="M18.5 6.5h2V12.5H12V16" />
        <rect x="10.5" y="16" width="3" height="5.5" rx="1" />
      </>
    ),
  },
  "tools:automotive-tools": {
    label: "Automotive Tools",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 6.5h0M17.2 10.3h0M15.2 16.4h0M8.8 16.4h0M6.8 10.3h0M12 12h0" />
      </>
    ),
  },
  "tools:hand-tools-other": { label: "Other Hand Tools", kind: "category", body: OTHER_BODY },
  // Power tools
  "tools:drills": {
    label: "Drills & Drivers",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 8l3.46 2v4L12 16l-3.46-2v-4z" />
      </>
    ),
  },
  "tools:saws": {
    label: "Saws",
    kind: "category",
    body: (
      <>
        <path d="M20.2 12L21.96 12.94L21.66 14.59L19.69 14.86L19.1 16.1L20.15 17.79L19.07 19.07L17.23 18.32L16.1 19.1L16.16 21.09L14.59 21.66L13.37 20.09L12 20.2L11.06 21.96L9.41 21.66L9.14 19.69L7.9 19.1L6.21 20.15L4.93 19.07L5.68 17.23L4.9 16.1L2.91 16.16L2.34 14.59L3.91 13.37L3.8 12L2.04 11.06L2.34 9.41L4.31 9.14L4.9 7.9L3.85 6.21L4.93 4.93L6.77 5.68L7.9 4.9L7.84 2.91L9.41 2.34L10.63 3.91L12 3.8L12.94 2.04L14.59 2.34L14.86 4.31L16.1 4.9L17.79 3.85L19.07 4.93L18.32 6.77L19.1 7.9L21.09 7.84L21.66 9.41L20.09 10.63Z" />
        <circle cx="12" cy="12" r="1.5" />
      </>
    ),
  },
  "tools:grinders": {
    label: "Grinders & Cutters",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="6" width="13" height="6" rx="3" />
        <rect x="15.5" y="6" width="4" height="6" rx="1" />
        <path d="M17.5 12v3.5" />
        <ellipse cx="17.5" cy="18" rx="4.5" ry="1.75" />
      </>
    ),
  },
  "tools:sanders-polishers": {
    label: "Sanders & Polishers",
    kind: "category",
    body: (
      <>
        <path d="M6 13a6 6 0 0 1 12 0z" />
        <rect x="4" y="13" width="16" height="4" rx="1" />
        <path d="M12 7V4M9 20.5h6" />
      </>
    ),
  },
  "tools:demolition": {
    label: "Rotary Hammers & Demolition",
    kind: "category",
    body: (
      <>
        <path d="M5.5 4h13" />
        <rect x="9" y="4" width="6" height="9" rx="1" />
        <path d="M12 13v8M6.5 21.5h11" />
      </>
    ),
  },
  "tools:welding-tools": {
    label: "Welding & Soldering Equipment",
    kind: "category",
    body: (
      <>
        <rect x="9" y="2.5" width="6" height="9.5" rx="3" />
        <rect x="10.5" y="12" width="3" height="3" rx="0.5" />
        <path d="M12 15v6l0.5 0.5" />
      </>
    ),
  },
  "tools:power-tools-other": { label: "Other Power Tools", kind: "category", body: OTHER_BODY },
  // Measurement
  "tools:tape-rules": {
    label: "Tape Measures & Rules",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="8" width="19" height="8" rx="1" />
        <path d="M6 8v3M10 8v4M14 8v3M18 8v4" />
      </>
    ),
  },
  "tools:levels-squares": {
    label: "Levels & Squares",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="8.5" width="19" height="7" rx="1" />
        <rect x="8.5" y="10.5" width="7" height="3" rx="1.5" />
        <path d="M11 10.5v3M13 10.5v3" />
      </>
    ),
  },
  "tools:precision-measure": {
    label: "Calipers & Micrometers",
    kind: "category",
    body: (
      <>
        <rect x="3" y="3" width="18" height="4.5" rx="0.75" />
        <path d="M6 7.5V21M14 7.5V21M10 4.5v1.5" />
      </>
    ),
  },
  "tools:test-instruments": {
    label: "Test & Detection Instruments",
    kind: "category",
    body: (
      <>
        <rect x="5.5" y="2.5" width="13" height="19" rx="2" />
        <rect x="8.5" y="5.5" width="7" height="4" rx="0.5" />
        <circle cx="12" cy="15" r="2.5" />
      </>
    ),
  },
  "tools:measurement-other": { label: "Other Measurement Tools", kind: "category", body: OTHER_BODY },
  // Accessories & consumables
  "tools:drill-bits": {
    label: "Drill Bits & Holesaws",
    kind: "category",
    body: (
      <>
        <rect x="10.5" y="2.5" width="3" height="5" rx="0.5" />
        <path d="M10.5 7.5v10L12 21.5l1.5-4v-10" />
        <path d="M10.5 10.5l3 1.5M10.5 14l3 1.5" />
      </>
    ),
  },
  "tools:blades-discs": {
    label: "Blades & Cutting Discs",
    kind: "category",
    body: (
      <>
        <path d="M2.5 16 6.5 8h15v8z" />
        <path d="M10.5 12h7" />
      </>
    ),
  },
  "tools:abrasives": {
    label: "Abrasives",
    kind: "category",
    body: (
      <>
        <rect x="4.5" y="3.5" width="15" height="17" rx="1" />
        <path d="M8 8h0M12 8h0M16 8h0M10 12h0M14 12h0M8 16h0M12 16h0M16 16h0" />
      </>
    ),
  },
  "tools:tool-storage": {
    label: "Tool Storage & Workshop",
    kind: "category",
    body: (
      <>
        <rect x="4.5" y="3" width="15" height="18" rx="1.5" />
        <path d="M4.5 9h15M4.5 15h15M10 6h4M10 12h4M10 18h4" />
      </>
    ),
  },
  "tools:work-lights": {
    label: "Work Lights & Torches",
    kind: "category",
    body: (
      <>
        <path d="M8 3.5h8l1.5 4h-11z" />
        <rect x="9.5" y="7.5" width="5" height="14" rx="1.5" />
        <path d="M12 11v3" />
        <path d="M3 3.5l2 1.5M21 3.5l-2 1.5" />
      </>
    ),
  },
  "tools:consumables-other": { label: "Other Accessories", kind: "category", body: OTHER_BODY },
  // Pneumatic
  "tools:air-tools": {
    label: "Air Tools",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="4.5" width="13" height="7" rx="2" />
        <path d="M16.5 8h4" />
        <path d="M8 11.5v7h5v-7M10.5 18.5v3" />
      </>
    ),
  },
  "tools:compressors": {
    label: "Compressors",
    kind: "category",
    body: (
      <>
        <rect x="3" y="8" width="15" height="9" rx="4.5" />
        <rect x="6.5" y="3" width="8" height="4" rx="0.75" />
        <path d="M18 12h3.5M6 17v3M15 17v3" />
      </>
    ),
  },
  "tools:pneumatic-accessories": {
    label: "Air Fittings & Hoses",
    kind: "category",
    body: (
      <>
        <path d="M2.5 12q1.75-4.5 3.5 0t3.5 0" />
        <rect x="9.5" y="8.5" width="5" height="7" rx="0.5" />
        <path d="M14.5 12h3" />
        <rect x="17.5" y="10" width="4" height="4" rx="0.5" />
      </>
    ),
  },
};
