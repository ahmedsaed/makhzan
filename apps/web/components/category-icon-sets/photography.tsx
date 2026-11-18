import type { Glyph } from "./types";

/** Photography: no schematic symbols, so the categories are the things themselves. */
export const PHOTOGRAPHY_ICONS: Record<string, Glyph> = {
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
