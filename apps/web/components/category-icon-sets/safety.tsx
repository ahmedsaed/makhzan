import type { Glyph } from "./types";

/** Safety: what a person wears for groups and categories alike, and the signs and fire gear around them. */
export const SAFETY_ICONS: Record<string, Glyph> = {
  // Groups
  "safety:personal-protection": {
    label: "Personal Protection",
    kind: "group",
    body: (
      <>
        <path d="M12 3 20 6v6c0 4.5-3.5 8-8 9-4.5-1-8-4.5-8-9V6z" />
        <path d="M8.5 12l2.5 2.5 4.5-5" />
      </>
    ),
  },
  "safety:fire-protection": {
    label: "Fire Protection",
    kind: "group",
    body: (
      <>
        <path d="M12 21a6 6 0 0 1-6-6c0-3 2-5 3.5-7 .5 2 1.5 2.5 2.5 3 0-3 1-5.5 3-8 3 2.5 5 5.5 5 9.5a6 6 0 0 1-6 6z" />
        <path d="M12 21a2.5 2.5 0 0 1-2.5-2.5c0-1.5 1.5-2.5 2.5-4 1 1.5 2.5 2.5 2.5 4A2.5 2.5 0 0 1 12 21z" />
      </>
    ),
  },
  // Personal protection
  "safety:gloves": {
    label: "Gloves",
    kind: "category",
    body: (
      <>
        <path d="M7 21v-5.5L4.8 12.2a1.25 1.25 0 0 1 2-1.5l1.7 2V5.5a1.25 1.25 0 0 1 2.5 0V4a1.25 1.25 0 0 1 2.5 0v1.5a1.25 1.25 0 0 1 2.5 0V8a1.25 1.25 0 0 1 2.5 0v7L16 19v2z" />
        <path d="M7 17.5h9" />
      </>
    ),
  },
  "safety:safety-footwear": {
    label: "Safety Footwear",
    kind: "category",
    body: (
      <>
        <path d="M5.5 3.5h6v8.5l7 3a2 2 0 0 1 1.5 2v3.5H5.5z" />
        <path d="M5.5 17.5H20M5.5 7h6" />
      </>
    ),
  },
  "safety:eye-protection": {
    label: "Eye Protection",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="8" width="8.5" height="8" rx="3.5" />
        <rect x="13" y="8" width="8.5" height="8" rx="3.5" />
        <path d="M11 12h2" />
      </>
    ),
  },
  "safety:head-protection": {
    label: "Head Protection",
    kind: "category",
    body: (
      <>
        <path d="M4 17.5C4 11.5 7.5 7.5 12.5 7.5c4 0 6.5 2.5 7 6.5l2 1v2.5z" />
        <path d="M12.5 7.5v10" />
      </>
    ),
  },
  "safety:welding-protection": {
    label: "Welding Protection",
    kind: "category",
    body: (
      <>
        <path d="M9 3.5v5H6.5L5 21h14L17.5 8.5H15v-5" />
        <path d="M9 3.5q3-1.5 6 0" />
        <rect x="9.5" y="14" width="5" height="3.5" rx="0.5" />
      </>
    ),
  },
  "safety:hearing-protection": {
    label: "Hearing Protection",
    kind: "category",
    body: (
      <>
        <path d="M5 13v-2a7 7 0 0 1 14 0v2" />
        <rect x="3.5" y="12.5" width="4" height="7" rx="1.5" />
        <rect x="16.5" y="12.5" width="4" height="7" rx="1.5" />
      </>
    ),
  },
  "safety:respiratory": {
    label: "Respiratory Protection",
    kind: "category",
    body: (
      <>
        <path d="M4 9.5C6.5 7.5 9 7 12 7s5.5.5 8 2.5v2c0 4-3.5 8-8 8s-8-4-8-8z" />
        <circle cx="8" cy="13.5" r="2.25" />
        <circle cx="16" cy="13.5" r="2.25" />
        <path d="M4 10H2M20 10h2" />
      </>
    ),
  },
  "safety:workwear": {
    label: "Workwear & Hi-Vis",
    kind: "category",
    body: (
      <>
        <path d="M15.5 3.5 21 6.5 19 10l-2-1V21H7V9l-2 1-2-3.5 5.5-3a3.5 3.5 0 0 0 7 0z" />
        <path d="M7 14h10M7 17.5h10" />
      </>
    ),
  },
  "safety:knee-protection": {
    label: "Knee Protection",
    kind: "category",
    body: (
      <>
        <path d="M7.5 4h9v9a4.5 4.5 0 0 1-9 0z" />
        <path d="M7.5 7.5H3M16.5 7.5H21M7.5 11H3M16.5 11H21M10 14.5a2 2 0 0 0 4 0" />
      </>
    ),
  },
  "safety:first-aid": {
    label: "First Aid",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="6.5" width="17" height="13" rx="2" />
        <path d="M9 6.5v-2h6v2M12 10v6M9 13h6" />
      </>
    ),
  },
  // Fire protection
  "safety:safety-signage": {
    label: "Safety Signage",
    kind: "category",
    body: (
      <>
        <path d="M12 3.5 21.5 20h-19z" />
        <path d="M12 9.5v5M12 17.25h0" />
      </>
    ),
  },
  "safety:fire-extinguishers": {
    label: "Fire Extinguishers",
    kind: "category",
    body: (
      <>
        <rect x="7.5" y="8" width="9" height="13" rx="2.5" />
        <path d="M10.5 8V5.5h3V8M8 4.5h8M7.5 13h9" />
        <path d="M13.5 6.5H18a2 2 0 0 1 2 2V15" />
      </>
    ),
  },
  "safety:fire-alarms": {
    label: "Fire Alarms & Evacuation",
    kind: "category",
    body: (
      <>
        <path d="M6 17v-6a6 6 0 0 1 12 0v6l1.5 1.5h-15z" />
        <path d="M10.5 21h3M12 3V2" />
      </>
    ),
  },
  "safety:fire-cabinets": {
    label: "Cabinets, Reels & Racks",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="3.5" width="17" height="17" rx="2" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.5" />
      </>
    ),
  },
  "safety:rescue-equipment": {
    label: "Rescue Equipment",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="3.5" />
        <path d="M6 6l3.5 3.5M18 6l-3.5 3.5M6 18l3.5-3.5M18 18l-3.5-3.5" />
      </>
    ),
  },
};
