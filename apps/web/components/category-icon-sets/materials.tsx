import type { Glyph } from "./types";

/** Materials: sheets, resins, flooring and building stock, drawn as the stuff or its commonest form. */
export const MATERIALS_ICONS: Record<string, Glyph> = {
  // Groups
  "materials:rubber-plastics": {
    label: "Rubber & Plastics",
    kind: "group",
    body: (
      <>
        <path d="M3 8 12 3.5 21 8l-9 4.5z" />
        <path d="M3 12l9 4.5 9-4.5M3 16l9 4.5 9-4.5" />
      </>
    ),
  },
  "materials:resins-casting": {
    label: "Resins & Casting",
    kind: "group",
    body: (
      <>
        <path d="M5 6.5h9.5v13a1.5 1.5 0 0 1-1.5 1.5H6.5A1.5 1.5 0 0 1 5 19.5z" />
        <path d="M5 9.5H3v7h2M14.5 8.5h3l2.5-3" />
        <path d="M20 11c-1 1.5-1.5 2.25-1.5 3a1.5 1.5 0 0 0 3 0c0-.75-.5-1.5-1.5-3z" />
      </>
    ),
  },
  "materials:flooring": {
    label: "Flooring",
    kind: "group",
    body: (
      <>
        <path d="M3 19h18L17 8H7z" />
        <path d="M9.33 8 8 19M14.67 8 16 19M5 13.5h14" />
      </>
    ),
  },
  "materials:building-materials": {
    label: "Building Materials",
    kind: "group",
    body: (
      <>
        <rect x="3" y="6.5" width="18" height="11" rx="1" />
        <rect x="6.5" y="10" width="4" height="4" />
        <rect x="13.5" y="10" width="4" height="4" />
      </>
    ),
  },
  // Rubber & plastics
  "materials:rubber-sheet": {
    label: "Rubber Sheet",
    kind: "category",
    body: (
      <>
        <path d="M3 10 12 5.5l9 4.5-9 4.5z" />
        <path d="M3 10v3.5l9 4.5 9-4.5V10M12 14.5V18" />
      </>
    ),
  },
  "materials:anti-vibration-pads": {
    label: "Anti-Vibration Pads",
    kind: "category",
    body: (
      <>
        <rect x="8.5" y="4" width="7" height="6" rx="1" />
        <path d="M10 10l1.25 1.5L10 13l1.25 1.5M14 10l-1.25 1.5L14 13l-1.25 1.5" />
        <rect x="4" y="16" width="16" height="4" rx="1" />
      </>
    ),
  },
  "materials:membranes": {
    label: "Membranes",
    kind: "category",
    body: (
      <>
        <path d="M7 4v3.5M12 3v4.5M17 4v3.5" />
        <path d="M3 11.5h18" />
        <rect x="3" y="14.5" width="18" height="5.5" rx="1" />
      </>
    ),
  },
  // Resins
  "materials:epoxy-resins": {
    label: "Epoxy Resins",
    kind: "category",
    body: (
      <>
        <rect x="4.5" y="8.5" width="6" height="12" rx="1" />
        <rect x="13.5" y="8.5" width="6" height="12" rx="1" />
        <path d="M7.5 8.5V4M16.5 8.5V4M4.5 17h6M13.5 17h6" />
      </>
    ),
  },
  "materials:polyester-resins": {
    label: "Polyester Resins",
    kind: "category",
    body: (
      <>
        <rect x="4" y="4" width="16" height="16" rx="1" />
        <path d="M4 9.33h16M4 14.67h16M9.33 4v16M14.67 4v16" />
      </>
    ),
  },
  "materials:casting-pigments": {
    label: "Pigments & Colourants",
    kind: "category",
    body: (
      <>
        <path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.5 0 2-1 1.5-2.2-.5-1.3.2-2.3 1.5-2.3H17a3.5 3.5 0 0 0 3.5-3.5C20.5 7 16.8 3.5 12 3.5z" />
        <path d="M7.5 11h0M10 7.5h0M15 7.5h0" />
      </>
    ),
  },
  // Flooring
  "materials:decorative-aggregates": {
    label: "Decorative Stone & Sand",
    kind: "category",
    body: (
      <>
        <path d="M3 20.5c0-3 2-4.5 4.5-4.5s4.5 1.5 4.5 4.5z" />
        <path d="M12 20.5c0-3 2-4.5 4.5-4.5s4.5 1.5 4.5 4.5z" />
        <path d="M7.5 16c0-3.5 2-6 4.5-6s4.5 2.5 4.5 6" />
      </>
    ),
  },
  "materials:safety-flooring": {
    label: "Safety Flooring",
    kind: "category",
    body: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="1.5" />
        <path d="M6.5 9.5l3-3M14.5 9.5l3-3M6.5 17.5l3-3M14.5 17.5l3-3" />
      </>
    ),
  },
  "materials:sports-flooring": {
    label: "Sports & Play Flooring",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="1.5" />
        <path d="M12 5v14" />
        <circle cx="12" cy="12" r="2.75" />
      </>
    ),
  },
  "materials:floor-mats": {
    label: "Mats",
    kind: "category",
    body: (
      <>
        <path d="M6 7.5h16l-2.5 9H3.5z" />
        <path d="M8 10h11l-1.25 4H6.75z" />
      </>
    ),
  },
  // Building
  "materials:insulation": {
    label: "Insulation",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="4.5" width="17" height="15" rx="1" />
        <path d="M7 9.5q1.25-2.25 2.5 0t2.5 0 2.5 0 2.5 0M7 14.5q1.25-2.25 2.5 0t2.5 0 2.5 0 2.5 0" />
      </>
    ),
  },
  "materials:parking-supplies": {
    label: "Parking & Traffic",
    kind: "category",
    body: (
      <>
        <path d="M10 3.5h4L17.5 18h-11z" />
        <path d="M3.5 18v3h17v-3M8.2 11h7.6" />
      </>
    ),
  },
  "materials:metal-stock": {
    label: "Metal Stock",
    kind: "category",
    body: (
      <>
        <circle cx="7" cy="16.5" r="4" />
        <circle cx="17" cy="16.5" r="4" />
        <circle cx="12" cy="8.25" r="4" />
      </>
    ),
  },
};
