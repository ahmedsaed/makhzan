import { OTHER_BODY } from "./shared";
import type { Glyph } from "./types";

/** Garden: hand tools, mowers and watering. */
export const GARDEN_ICONS: Record<string, Glyph> = {
  // Groups
  "garden:garden-hand-tools": {
    label: "Garden Hand Tools",
    kind: "group",
    body: (
      <>
        <path d="M12 3.5c2.5 2.5 4 5 4 7.5 0 2-1.5 3.5-4 3.5s-4-1.5-4-3.5c0-2.5 1.5-5 4-7.5z" />
        <path d="M12 14.5v2" />
        <rect x="10" y="16.5" width="4" height="5" rx="2" />
      </>
    ),
  },
  "garden:garden-power-equipment": {
    label: "Garden Power Equipment",
    kind: "group",
    body: (
      <>
        <rect x="4" y="11.5" width="12" height="5" rx="1.5" />
        <path d="M14 11.5 19.5 4H22" />
        <circle cx="7" cy="19.25" r="1.75" />
        <circle cx="14" cy="19.25" r="1.75" />
      </>
    ),
  },
  "garden:irrigation": {
    label: "Irrigation",
    kind: "group",
    body: (
      <>
        <rect x="4" y="9" width="10" height="11" rx="1.5" />
        <path d="M14 16l5.5-7M18 7.5l3 2" />
        <path d="M7 9V6.5h5V9M21 13h0M21 16h0" />
      </>
    ),
  },
  // Tools
  "garden:digging-tools": {
    label: "Digging & Earth Tools",
    kind: "category",
    body: (
      <>
        <path d="M8 11.5h8l-.75 6L12 21l-3.25-3.5z" />
        <path d="M12 3v8.5M9 3h6" />
      </>
    ),
  },
  "garden:cutting-garden": {
    label: "Pruning & Cutting",
    kind: "category",
    body: (
      <>
        <path d="M4.5 20.5 12 10M8 21.5l5.5-9.5" />
        <path d="M12 10 18.5 3.5M13.5 12c3.5 0 6.5-2.5 6.5-6" />
      </>
    ),
  },
  "garden:mowers-trimmers": {
    label: "Mowers & Trimmers",
    kind: "category",
    body: (
      <>
        <path d="M19.5 3.5 9.5 16" />
        <ellipse cx="8" cy="18.5" rx="3.5" ry="1.75" />
        <path d="M3 18.5h1.5M11.5 18.5H13" />
      </>
    ),
  },
  "garden:garden-power-other": {
    label: "Other Garden Power Tools",
    kind: "category",
    body: OTHER_BODY,
  },
  "garden:sprinklers": {
    label: "Sprinklers & Watering",
    kind: "category",
    body: (
      <>
        <path d="M10 21v-6h4v6M12 15v-3.5" />
        <path d="M12 11 6 5M12 11V3.5M12 11l6-6" />
        <path d="M3.5 8.5h0M20.5 8.5h0" />
      </>
    ),
  },
};
