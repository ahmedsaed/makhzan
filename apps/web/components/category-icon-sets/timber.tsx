import type { Glyph } from "./types";

/** Timber: boards for the groups, a leaf, tree, fruit or grain to tell each species apart. */
export const TIMBER_ICONS: Record<string, Glyph> = {
  // Groups
  "timber:hardwood": {
    label: "Hardwood",
    kind: "group",
    body: (
      <>
        <rect x="3" y="3.5" width="18" height="4" rx="0.75" />
        <rect x="3" y="9.5" width="18" height="4" rx="0.75" />
        <rect x="3" y="15.5" width="18" height="4" rx="0.75" />
      </>
    ),
  },
  "timber:wood-finishes": {
    label: "Wood Finishes",
    kind: "group",
    body: (
      <>
        <rect x="4" y="11" width="11" height="10" rx="1.5" />
        <path d="M3.5 11h12" />
        <path d="M18 3v7.5" />
        <rect x="16.5" y="10.5" width="3" height="3" />
        <path d="M16.5 13.5V18h3v-4.5" />
      </>
    ),
  },
  // Species
  "timber:oak": {
    label: "Oak",
    kind: "category",
    body: (
      <>
        <path d="M12 3.5c1.5 0 2 1.5 3 1.5s2.5-.5 2.5 1.5c0 1-1.5 1.5-1.5 2.5s2 1.5 2 3c0 2-2.5 1.5-3 2.5-.5 1.5-1 3-3 3s-2.5-1.5-3-3c-.5-1-3-.5-3-2.5 0-1.5 2-2 2-3S6.5 7.5 6.5 6.5C6.5 4.5 8 5 9 5s1.5-1.5 3-1.5z" />
        <path d="M12 8v13" />
      </>
    ),
  },
  "timber:teak": {
    label: "Teak",
    kind: "category",
    body: (
      <>
        <path d="M12 3c5 2 7.5 6 7.5 10.5S16 21 12 21s-7.5-3.5-7.5-7.5S7 5 12 3z" />
        <path d="M12 21V8M12 12.5l3.25-3M12 16l4-3.5M12 12.5l-3.25-3M12 16l-4-3.5" />
      </>
    ),
  },
  "timber:mahogany": {
    label: "Mahogany",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.5" />
      </>
    ),
  },
  "timber:pine": {
    label: "Pine",
    kind: "category",
    body: (
      <>
        <path d="M12 2.5 7.5 9H10L6 15h12l-4-6h2.5z" />
        <path d="M12 15v6" />
      </>
    ),
  },
  "timber:walnut": {
    label: "Walnut",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 3.5c-2 3 2 5 0 8.5s2 5.5 0 8.5" />
      </>
    ),
  },
  "timber:wenge": {
    label: "Wenge",
    kind: "category",
    body: (
      <>
        <rect x="3" y="6.5" width="18" height="11" rx="1.5" />
        <path d="M6.5 10.5H13M11 13.5h6.5" />
      </>
    ),
  },
  "timber:padauk": {
    label: "Padauk",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="9.5" r="6.5" />
        <path d="M12 16v5.5M9 21.5h6" />
      </>
    ),
  },
  "timber:engineered-wood": {
    label: "Engineered Wood",
    kind: "category",
    body: (
      <>
        <path d="M3 9 12 5l9 4-9 4z" />
        <path d="M3 9v3l9 4 9-4V9M12 13v3" />
      </>
    ),
  },
  // Finishes
  "timber:wood-stains": {
    label: "Stains & Dyes",
    kind: "category",
    body: (
      <>
        <rect x="9.5" y="3" width="5" height="3" rx="0.75" />
        <path d="M10 6v2.5M14 6v2.5M8 8.5h8" />
        <rect x="6.5" y="8.5" width="11" height="12.5" rx="2" />
        <path d="M12 12c-1.2 1.5-2 2.25-2 3.25a2 2 0 0 0 4 0c0-1-.8-1.75-2-3.25z" />
      </>
    ),
  },
  "timber:wood-oils-waxes": {
    label: "Oils & Waxes",
    kind: "category",
    body: (
      <>
        <ellipse cx="12" cy="9" rx="8" ry="3" />
        <path d="M4 9v5c0 1.7 3.6 3 8 3s8-1.3 8-3V9" />
        <path d="M8.5 9.5q3.5 1.25 7 0" />
      </>
    ),
  },
  "timber:wood-fillers": {
    label: "Fillers",
    kind: "category",
    body: (
      <>
        <rect x="15" y="10" width="6.5" height="4" rx="1.5" />
        <path d="M15 12h-2M13 9H5l-2 3 2 3h8" />
        <path d="M6 19.5h6" />
      </>
    ),
  },
};
