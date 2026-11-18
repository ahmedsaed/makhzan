import type { Glyph } from "./types";

/** Cleaning: washers, vacuums and floor machines. */
export const CLEANING_ICONS: Record<string, Glyph> = {
  // Groups
  "cleaning:cleaning-equipment": {
    label: "Cleaning Equipment",
    kind: "group",
    body: (
      <>
        <path d="M5.5 10h13l-1.5 11H7z" />
        <path d="M4.5 10h15M8 10V7a4 4 0 0 1 8 0v3" />
      </>
    ),
  },
  "cleaning:cleaning-accessories": {
    label: "Accessories",
    kind: "group",
    body: (
      <>
        <rect x="3.5" y="12" width="17" height="4" rx="1" />
        <path d="M12 12V3M9.5 3h5M5 16v3M9 16v3M13 16v3M17 16v3" />
      </>
    ),
  },
  // Equipment
  "cleaning:pressure-washers": {
    label: "Pressure Washers",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="9.5" width="11" height="11" rx="2" />
        <path d="M6 9.5V6h6v3.5M14.5 14h3.5a2 2 0 0 0 2-2V6" />
        <path d="M19 3h0M21.5 3h0M20 1.5h0" />
      </>
    ),
  },
  "cleaning:vacuum-cleaners": {
    label: "Vacuum Cleaners",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="12" width="12" height="7" rx="3.5" />
        <path d="M12 12V8a3.5 3.5 0 0 1 3.5-3.5H17M17 4.5l4 6.5M18.5 11h4" />
      </>
    ),
  },
  "cleaning:floor-machines": {
    label: "Floor Machines",
    kind: "category",
    body: (
      <>
        <rect x="6" y="9" width="9" height="9" rx="2" />
        <path d="M15 11 20 5M18 4h4" />
        <ellipse cx="10.5" cy="20.25" rx="7" ry="1.5" />
      </>
    ),
  },
  "cleaning:foam-machines": {
    label: "Foam Machines",
    kind: "category",
    body: (
      <>
        <rect x="7" y="3" width="6" height="8" rx="1.5" />
        <rect x="4" y="11" width="12" height="4" rx="1" />
        <path d="M16 13h2" />
        <circle cx="20" cy="13" r="1.5" />
        <circle cx="17" cy="18" r="1.75" />
        <circle cx="12.5" cy="19.5" r="1.5" />
      </>
    ),
  },
  "cleaning:washer-accessories": {
    label: "Washer Accessories",
    kind: "category",
    body: (
      <>
        <path d="M2.5 12h6.5M9 9.5l5-2v9l-5-2z" />
        <path d="M17 8h4M17 12h5M17 16h4" />
      </>
    ),
  },
};
