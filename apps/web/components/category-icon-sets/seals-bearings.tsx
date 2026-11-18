import type { Glyph } from "./types";

/** Seals & bearings: rings, sections through a housing, and what flows through filters. */
export const SEALS_BEARINGS_ICONS: Record<string, Glyph> = {
  // Groups
  "seals-bearings:sealing": {
    label: "Seals & Gaskets",
    kind: "group",
    body: (
      <>
        <ellipse cx="12" cy="9.5" rx="8.5" ry="4" />
        <ellipse cx="12" cy="9.5" rx="4" ry="1.75" />
        <path d="M3.5 9.5v4a8.5 4 0 0 0 17 0v-4" />
      </>
    ),
  },
  "seals-bearings:bearings-transmission": {
    label: "Bearings & Transmission",
    kind: "group",
    body: (
      <>
        <path d="M19.2 12L21.41 13.34L20.78 15.64L18.2 15.67L17.09 17.09L17.7 19.6L15.64 20.78L13.79 18.97L12 19.2L10.66 21.41L8.36 20.78L8.33 18.2L6.91 17.09L4.4 17.7L3.22 15.64L5.03 13.79L4.8 12L2.59 10.66L3.22 8.36L5.8 8.33L6.91 6.91L6.3 4.4L8.36 3.22L10.21 5.03L12 4.8L13.34 2.59L15.64 3.22L15.67 5.8L17.09 6.91L19.6 6.3L20.78 8.36L18.97 10.21Z" />
        <circle cx="12" cy="12" r="3" />
      </>
    ),
  },
  "seals-bearings:filtration": {
    label: "Filtration",
    kind: "group",
    body: (
      <>
        <ellipse cx="12" cy="5" rx="5.5" ry="2" />
        <path d="M6.5 5v14a5.5 2 0 0 0 11 0V5" />
        <path d="M9 8v10.5M12 8.5v11M15 8v10.5" />
      </>
    ),
  },
  "seals-bearings:lubrication": {
    label: "Lubrication",
    kind: "group",
    body: (
      <>
        <rect x="4" y="10.5" width="11" height="9.5" rx="1.5" />
        <path d="M7.5 10.5V8h4v2.5" />
        <path d="M15 13l6.5-6.5" />
        <path d="M4 12.5H2.5V17H4" />
        <path d="M21.5 11h0" />
      </>
    ),
  },
  "seals-bearings:sealing-materials": {
    label: "Sealing Materials",
    kind: "group",
    body: (
      <>
        <path d="M9 5.5h12v13H9" />
        <circle cx="9" cy="12" r="6.5" />
        <circle cx="9" cy="12" r="2" />
      </>
    ),
  },
  "seals-bearings:machine-fittings": {
    label: "Fittings & Spares",
    kind: "group",
    body: (
      <>
        <path d="M8 3h8v4.5H8z" />
        <path d="M9.5 7.5v13.5h5V7.5" />
        <path d="M9.5 11.5l5 1.5M9.5 15.5l5 1.5" />
      </>
    ),
  },
  // Sealing
  "seals-bearings:o-rings": {
    label: "O-Rings",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="5.5" />
      </>
    ),
  },
  "seals-bearings:oil-seals": {
    label: "Oil Seals",
    kind: "category",
    body: (
      <>
        <rect x="4.5" y="4" width="7" height="16" rx="1" />
        <path d="M11.5 8.5 16 11v2l-4.5 2.5" />
        <path d="M20.5 3v18" />
      </>
    ),
  },
  "seals-bearings:mechanical-seals": {
    label: "Mechanical Seals",
    kind: "category",
    body: (
      <>
        <path d="M2.5 12l1.5-3.5 2.5 7 2.5-7 1.5 3.5" />
        <rect x="12.5" y="4.5" width="3" height="15" rx="0.5" />
        <rect x="18.5" y="4.5" width="3" height="15" rx="0.5" />
      </>
    ),
  },
  "seals-bearings:gland-packing": {
    label: "Gland Packing",
    kind: "category",
    body: (
      <>
        <rect x="6" y="3.5" width="12" height="17" rx="1" />
        <path d="M6 9.2h12M6 14.8h12" />
      </>
    ),
  },
  "seals-bearings:gaskets": {
    label: "Gaskets",
    kind: "category",
    body: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="3.5" />
        <circle cx="12" cy="12" r="4.5" />
        <path d="M6.5 6.5h0M17.5 6.5h0M6.5 17.5h0M17.5 17.5h0" />
      </>
    ),
  },
  // Bearings & transmission
  "seals-bearings:bearings": {
    label: "Bearings",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 6.5h0M16.76 9.25h0M16.76 14.75h0M12 17.5h0M7.24 14.75h0M7.24 9.25h0" />
      </>
    ),
  },
  "seals-bearings:couplings": {
    label: "Couplings",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="7" width="7" height="10" rx="1.5" />
        <rect x="14.5" y="7" width="7" height="10" rx="1.5" />
        <path d="M9.5 10h5M9.5 14h5" />
      </>
    ),
  },
  // Filtration
  "seals-bearings:air-filters": {
    label: "Air Filters",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5.5" width="18" height="13" rx="1" />
        <path d="M6 8.5l2 7 2-7 2 7 2-7 2 7 2-7" />
      </>
    ),
  },
  "seals-bearings:oil-filters": {
    label: "Oil Filters",
    kind: "category",
    body: (
      <>
        <rect x="7.5" y="3" width="9" height="3" rx="0.75" />
        <rect x="5.5" y="6" width="13" height="15" rx="2.5" />
        <path d="M12 9.5c-2 2.5-2.5 3.5-2.5 5a2.5 2.5 0 0 0 5 0c0-1.5-.5-2.5-2.5-5z" />
      </>
    ),
  },
  "seals-bearings:fuel-filters": {
    label: "Fuel Filters",
    kind: "category",
    body: (
      <>
        <rect x="6" y="6.5" width="12" height="11" rx="2.5" />
        <path d="M2.5 12H6M18 12h3.5" />
        <path d="M9.5 12h5M12.5 9.75 15 12l-2.5 2.25" />
      </>
    ),
  },
  "seals-bearings:hydraulic-filters": {
    label: "Hydraulic Filters",
    kind: "category",
    body: (
      <>
        <rect x="4.5" y="3" width="15" height="5" rx="1" />
        <rect x="7" y="8" width="10" height="13" rx="3" />
        <path d="M12 11.5v5M10 14.5l2 2 2-2" />
      </>
    ),
  },
  "seals-bearings:water-filters": {
    label: "Water Filters",
    kind: "category",
    body: (
      <>
        <path d="M12 2.5c-4 4.5-6 7.5-6 10.5a6 6 0 0 0 12 0c0-3-2-6-6-10.5z" />
        <path d="M9 14.5q1.5-1.5 3 0t3 0" />
      </>
    ),
  },
  "seals-bearings:filter-regulators": {
    label: "Filter Regulators",
    kind: "category",
    body: (
      <>
        <rect x="10" y="3" width="4" height="4" rx="0.75" />
        <rect x="7" y="7" width="10" height="5" rx="0.75" />
        <rect x="8" y="12" width="8" height="8" rx="2.5" />
        <path d="M2.5 9.5H7M17 9.5h4.5" />
      </>
    ),
  },
  // Lubrication
  "seals-bearings:oil-cups": {
    label: "Oil Cups & Lubricators",
    kind: "category",
    body: (
      <>
        <path d="M9.5 3h5" />
        <circle cx="12" cy="10" r="5.5" />
        <path d="M9 11q1.5-1.5 3 0t3 0" />
        <rect x="9" y="16" width="6" height="3.5" rx="0.5" />
        <path d="M10.5 19.5v2" />
      </>
    ),
  },
  "seals-bearings:auto-lubricators": {
    label: "Automatic Lubricators",
    kind: "category",
    body: (
      <>
        <rect x="9" y="2.5" width="6" height="4" rx="0.75" />
        <rect x="7" y="6.5" width="10" height="12" rx="2" />
        <path d="M10 10.5h4M10 14h4M12 18.5v3" />
      </>
    ),
  },
  // Sealing materials
  "seals-bearings:ptfe-stock": {
    label: "PTFE Sheet & Rod",
    kind: "category",
    body: (
      <>
        <ellipse cx="5" cy="8.5" rx="1.5" ry="3" />
        <path d="M5 5.5h15M5 11.5h15" />
        <path d="M20 5.5a1.5 3 0 0 1 0 6" />
        <path d="M3 20.5h14.5L21 15.5H6.5z" />
      </>
    ),
  },
  "seals-bearings:graphite-mica": {
    label: "Graphite & Mica",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="9.5" width="12" height="11" rx="1" />
        <path d="M6.5 9.5v-3h12v9.5h-3" />
        <path d="M9.5 6.5v-3H21v9.5h-2.5" />
      </>
    ),
  },
  "seals-bearings:sealing-tape": {
    label: "Sealing Tape",
    kind: "category",
    body: (
      <>
        <circle cx="10" cy="11" r="7" />
        <circle cx="10" cy="11" r="2.5" />
        <path d="M10 18h4.5a3 3 0 0 1 3 3H21.5" />
      </>
    ),
  },
  // Fittings & spares
  "seals-bearings:sight-glasses": {
    label: "Sight Glasses",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M5.5 13.5q2.1-2 4.2 0t4.2 0 4.2 0" />
        <path d="M8 8.5a5 5 0 0 1 2.5-2" />
      </>
    ),
  },
  "seals-bearings:machine-spares": {
    label: "Machine Spares",
    kind: "category",
    body: (
      <>
        <path d="M12 4.5l6.06 3.5v8L12 19.5 5.94 16V8z" />
        <circle cx="12" cy="12" r="2.5" />
      </>
    ),
  },
};
