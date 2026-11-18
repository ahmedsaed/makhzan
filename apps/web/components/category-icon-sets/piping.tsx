import type { Glyph } from "./types";

/** Piping: the valve family in schematic symbols, so five valves stay five; groups as the parts themselves. */
export const PIPING_ICONS: Record<string, Glyph> = {
  // Groups
  "piping:valves": {
    label: "Valves",
    kind: "group",
    body: (
      <>
        <path d="M2.5 17h4M17.5 17h4" />
        <rect x="6.5" y="13" width="11" height="8" rx="1.5" />
        <path d="M12 13V7" />
        <ellipse cx="12" cy="5.5" rx="5" ry="1.5" />
      </>
    ),
  },
  "piping:flange-gaskets": {
    label: "Flange Gaskets",
    kind: "group",
    body: (
      <>
        <path d="M2.5 12h4M17.5 12h4" />
        <rect x="6.5" y="5" width="3" height="14" rx="0.75" />
        <rect x="14.5" y="5" width="3" height="14" rx="0.75" />
        <path d="M9.5 8h5M9.5 16h5M12 5v14" />
      </>
    ),
  },
  "piping:line-fittings": {
    label: "Fittings & Accessories",
    kind: "group",
    body: <path d="M2.5 10h6.5V3.5h6V10h6.5v6h-19z" />,
  },
  // Valves
  "piping:butterfly-valves": {
    label: "Butterfly Valves",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="14" r="6.5" />
        <path d="M12 7.5V3M9 3h6M8 9.5l8 9" />
      </>
    ),
  },
  "piping:ball-valves": {
    label: "Ball Valves",
    kind: "category",
    body: (
      <>
        <path d="M2.5 15h4.5M17 15h4.5" />
        <circle cx="12" cy="15" r="5" />
        <path d="M12 10V7h8" />
      </>
    ),
  },
  "piping:globe-valves": {
    label: "Globe Valves",
    kind: "category",
    body: (
      <>
        <path d="M2.5 16h4M17.5 16h4" />
        <circle cx="12" cy="16" r="5.5" />
        <path d="M12 10.5V4M8.5 4h7M9.5 12.5h5" />
      </>
    ),
  },
  "piping:gate-valves": {
    label: "Gate Valves",
    kind: "category",
    body: (
      <>
        <path d="M2.5 15.5H6M18 15.5h3.5" />
        <rect x="6" y="11" width="12" height="9.5" rx="2" />
        <path d="M12 11V4M8 4h8" />
        <path d="M9.5 11v5.5l2.5 2.5 2.5-2.5V11" />
      </>
    ),
  },
  "piping:check-valves": {
    label: "Check Valves",
    kind: "category",
    body: (
      <>
        <path d="M2.5 12h4.5M17 12h4.5" />
        <circle cx="12" cy="12" r="5" />
        <path d="M9.75 12h4.5M12.5 9.75l2.25 2.25-2.25 2.25" />
      </>
    ),
  },
  // Gaskets, strainers, joints
  "piping:sheet-gaskets": {
    label: "Gasket Sheets",
    kind: "category",
    body: (
      <>
        <path d="M4 4.5h16V16l-4.5 4.5H4z" />
        <path d="M15.5 20.5V16H20" />
        <circle cx="10" cy="11" r="3" />
      </>
    ),
  },
  "piping:spiral-wound-gaskets": {
    label: "Spiral Wound Gaskets",
    kind: "category",
    body: (
      <path d="M11.5 12a1.5 1.5 0 0 1 3 0 3.5 3.5 0 0 1-7 0 5.5 5.5 0 0 1 11 0 7.5 7.5 0 0 1-15 0" />
    ),
  },
  "piping:strainers": {
    label: "Strainers",
    kind: "category",
    body: (
      <>
        <path d="M3.5 5.5h17M5 5.5l2.5 14h9L19 5.5" />
        <path d="M8.5 5.5l1 14M12 5.5v14M15.5 5.5l-1 14M6.5 12h11" />
      </>
    ),
  },
  "piping:flexible-joints": {
    label: "Flexible Joints",
    kind: "category",
    body: (
      <>
        <path d="M2.5 10H6M2.5 14H6M13.5 10h8M13.5 14h8" />
        <path d="M6 10q1.25-5 2.5 0q1.25-5 2.5 0q1.25-5 2.5 0" />
        <path d="M6 14q1.25 5 2.5 0q1.25 5 2.5 0q1.25 5 2.5 0" />
      </>
    ),
  },
};
