import type { Glyph } from "./types";

/** Rigging: hoists and the things that hang from them. */
export const RIGGING_ICONS: Record<string, Glyph> = {
  // Groups
  "rigging:hoists": {
    label: "Hoists",
    kind: "group",
    body: (
      <>
        <rect x="7" y="3" width="10" height="8" rx="2" />
        <rect x="10.75" y="11" width="2.5" height="4" rx="1.25" />
        <path d="M12 15v2.5a2.75 2.75 0 1 0 2.75 2.75" />
      </>
    ),
  },
  "rigging:rigging-gear": {
    label: "Rigging Gear",
    kind: "group",
    body: (
      <>
        <path d="M7.5 4.5v8a4.5 4.5 0 0 0 9 0v-8" />
        <path d="M4.5 4.5h15M4.5 3v3M19.5 3v3" />
        <path d="M12 17.25v3.5" />
      </>
    ),
  },
  // Hoists
  "rigging:chain-hoists": {
    label: "Chain Hoists",
    kind: "category",
    body: (
      <>
        <rect x="8.5" y="2.5" width="7" height="8" rx="3.5" />
        <rect x="10.5" y="7.5" width="3" height="9" rx="1.5" />
        <rect x="8.5" y="13.5" width="7" height="8" rx="3.5" />
      </>
    ),
  },
  "rigging:lever-hoists": {
    label: "Lever Hoists",
    kind: "category",
    body: (
      <>
        <circle cx="11.5" cy="4.5" r="1.75" />
        <path d="M11.5 6.25V8.5" />
        <rect x="7" y="8.5" width="9" height="7" rx="2" />
        <path d="M16 11l5.5 9M11.5 15.5V17" />
        <circle cx="11.5" cy="19" r="2" />
      </>
    ),
  },
  "rigging:rope-hoists": {
    label: "Rope Hoists",
    kind: "category",
    body: (
      <>
        <rect x="3" y="4" width="18" height="7" rx="1" />
        <path d="M7 4v7M10.5 4v7M14 4v7M17.5 11v6" />
        <circle cx="17.5" cy="19" r="1.75" />
      </>
    ),
  },
  "rigging:trolleys": {
    label: "Trolleys & Clamps",
    kind: "category",
    body: (
      <>
        <path d="M2.5 4h19" />
        <circle cx="8" cy="7.5" r="1.5" />
        <circle cx="16" cy="7.5" r="1.5" />
        <rect x="6" y="9.5" width="12" height="4" rx="1" />
        <path d="M12 13.5v2.5" />
        <circle cx="12" cy="18.5" r="2" />
      </>
    ),
  },
  "rigging:rack-jacks": {
    label: "Rack & Pinion Jacks",
    kind: "category",
    body: (
      <>
        <rect x="8" y="3" width="8" height="16" rx="1" />
        <path d="M10 6.5h4M10 9.5h4M10 12.5h4M5.5 19h13M16 15.5h5.5" />
      </>
    ),
  },
  // Gear
  "rigging:slings": {
    label: "Slings",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="4.5" r="2" />
        <path d="M10.75 6 6 15M13.25 6 18 15" />
        <rect x="4" y="15" width="16" height="6" rx="1" />
      </>
    ),
  },
  "rigging:pulleys-blocks": {
    label: "Pulleys & Blocks",
    kind: "category",
    body: (
      <>
        <rect x="6" y="6" width="12" height="15" rx="6" />
        <circle cx="12" cy="14" r="3.25" />
        <path d="M12 14h0M12 6V2.5" />
      </>
    ),
  },
};
