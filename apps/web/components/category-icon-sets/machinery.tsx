import { OTHER_BODY } from "./shared";
import type { Glyph } from "./types";

/** Machinery: pumps, engines, lifting and concrete gear. Objects for groups, a part or symbol for each category. */
export const MACHINERY_ICONS: Record<string, Glyph> = {
  // Groups
  "machinery:pumps": {
    label: "Pumps",
    kind: "group",
    body: (
      <>
        <circle cx="11" cy="13" r="5.5" />
        <circle cx="11" cy="13" r="1.5" />
        <path d="M11 7.5V3h6" />
        <path d="M2.5 13h3M11 18.5V21M6.5 21h9" />
      </>
    ),
  },
  "machinery:power-equipment": {
    label: "Power Equipment",
    kind: "group",
    body: (
      <>
        <path d="M3 21V8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v13" />
        <path d="M3 21h18M3 11.5h18" />
        <path d="M12.75 13.5 10.5 17h3l-2.25 3.5" />
      </>
    ),
  },
  "machinery:lifting-handling": {
    label: "Lifting & Handling",
    kind: "group",
    body: (
      <>
        <rect x="3" y="9.5" width="9" height="6.5" rx="1.5" />
        <path d="M5 9.5V5.5h6V9.5" />
        <path d="M15 3v15.5M15 17h6.5" />
        <circle cx="6.5" cy="19" r="2" />
        <circle cx="12" cy="19" r="1.5" />
      </>
    ),
  },
  "machinery:concrete-equipment": {
    label: "Concrete Equipment",
    kind: "group",
    body: (
      <>
        <path d="M7.5 6h11l-2 7.5h-7z" />
        <circle cx="5" cy="16.5" r="2.75" />
        <path d="M18.5 6l3 3M16.5 13.5 18 21" />
      </>
    ),
  },
  "machinery:machinery-accessories": {
    label: "Machinery Accessories",
    kind: "group",
    body: (
      <>
        <rect x="4.5" y="3" width="15" height="18" rx="2" />
        <path d="M4.5 9h15M4.5 15h15" />
        <path d="M10 6h4M10 12h4M10 18h4" />
      </>
    ),
  },
  // Pumps
  "machinery:surface-pumps": {
    label: "Surface Pumps",
    kind: "category",
    body: (
      <>
        <rect x="3" y="8.5" width="8" height="8" rx="1.5" />
        <circle cx="16" cy="12.5" r="4" />
        <path d="M16 8.5V3.5M3 20h18" />
      </>
    ),
  },
  "machinery:submersible-pumps": {
    label: "Submersible Pumps",
    kind: "category",
    body: (
      <>
        <rect x="7.5" y="8" width="9" height="11.5" rx="2.5" />
        <path d="M12 8V2.5M10 16h4" />
        <path d="M2.5 12q1-1.25 2 0t2 0M17.5 12q1-1.25 2 0t2 0" />
      </>
    ),
  },
  "machinery:general-pumps": { label: "Other Pumps", kind: "category", body: OTHER_BODY },
  "machinery:pump-controllers": {
    label: "Pump Controllers",
    kind: "category",
    body: (
      <>
        <rect x="4" y="3.5" width="16" height="17" rx="2" />
        <circle cx="12" cy="10" r="3.5" />
        <path d="M12 10l1.75-1.75M8 17h0M12 17h0M16 17h0" />
      </>
    ),
  },
  // Power
  "machinery:generators": {
    label: "Generators",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M7.5 12q2.25-4.5 4.5 0t4.5 0" />
        <path d="M12 4V0.5M12 20v3.5" />
      </>
    ),
  },
  "machinery:air-compressors": {
    label: "Air Compressors",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="10" width="17" height="7" rx="3.5" />
        <rect x="7" y="4.5" width="7" height="5.5" rx="1" />
        <path d="M19.5 13.5h3M6 17v3.5M16 17v3.5" />
      </>
    ),
  },
  "machinery:engines-motors": {
    label: "Engines & Motors",
    kind: "category",
    body: (
      <>
        <rect x="8" y="2.5" width="8" height="9.5" rx="1" />
        <path d="M8 6.5h8M12 6.5v9" />
        <circle cx="12" cy="18.25" r="2.75" />
      </>
    ),
  },
  "machinery:machine-tools": {
    label: "Machine Tools & CNC",
    kind: "category",
    body: (
      <>
        <rect x="3" y="15" width="18" height="5" rx="1" />
        <rect x="3" y="5" width="6" height="10" rx="1" />
        <path d="M9 10h7.5M19.5 5.5V15" />
      </>
    ),
  },
  // Lifting
  "machinery:jacks": {
    label: "Jacks",
    kind: "category",
    body: (
      <>
        <rect x="7" y="18" width="10" height="3.5" rx="1" />
        <rect x="8.5" y="9.5" width="7" height="8.5" rx="1" />
        <path d="M12 9.5V5M9.5 5h5M15.5 15l6-4" />
      </>
    ),
  },
  "machinery:pallet-trucks": {
    label: "Pallet Trucks",
    kind: "category",
    body: (
      <>
        <rect x="4" y="6" width="9" height="8" rx="1" />
        <rect x="2.5" y="14" width="14" height="4" rx="1" />
        <circle cx="6" cy="20.25" r="1.5" />
        <path d="M16.5 15.5 19 5.5h3" />
      </>
    ),
  },
  "machinery:hydraulic-presses": {
    label: "Hydraulic Presses",
    kind: "category",
    body: (
      <>
        <path d="M3.5 21.5V2.5h17v19" />
        <rect x="9" y="5" width="6" height="4.5" rx="0.75" />
        <path d="M12 9.5V14M8 14h8" />
        <path d="M6.5 18h11" />
      </>
    ),
  },
  // Concrete
  "machinery:concrete-mixers": {
    label: "Concrete Mixers",
    kind: "category",
    body: (
      <>
        <path d="M9 3.5h6l3.5 6.5-2 4.5h-11L5.5 10z" />
        <path d="M5.5 10h13" />
        <path d="M8.5 14.5 6.5 21M15.5 14.5l2 6.5" />
      </>
    ),
  },
  "machinery:concrete-vibrators": {
    label: "Concrete Vibrators",
    kind: "category",
    body: (
      <>
        <rect x="10" y="12" width="4" height="9.5" rx="2" />
        <path d="M12 12V8.5c0-3.5-6-2.5-6-6" />
        <path d="M17 15q1.5 1.5 0 3M19.75 13.5q3 4 0 7" />
      </>
    ),
  },
  "machinery:concrete-saws": {
    label: "Concrete Saws",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="10.5" r="7" />
        <circle cx="12" cy="10.5" r="1.5" />
        <path d="M2.5 18.5h19M12 18.5V22" />
      </>
    ),
  },
  "machinery:concrete-tools": {
    label: "Concrete Tools",
    kind: "category",
    body: (
      <>
        <path d="M3 20.5 14.5 11l3.5 4z" />
        <path d="M15 12.5 20.5 5M18.5 4.5l3 2.5" />
      </>
    ),
  },
  // Accessories
  "machinery:lubrication-equipment": {
    label: "Lubrication Equipment",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5.5" width="13" height="6" rx="2" />
        <path d="M16 8.5h4.5M20.5 6.5v4" />
        <path d="M6.5 11.5 5.5 20h3.5l1-8.5" />
      </>
    ),
  },
  "machinery:hydraulic-components": {
    label: "Hydraulic Components",
    kind: "category",
    body: (
      <>
        <circle cx="11" cy="13" r="6.5" />
        <path d="M11 9.5 14 14.5H8z" />
        <path d="M11 6.5V2M17.5 13H22" />
      </>
    ),
  },
  "machinery:machine-connectors": {
    label: "Machine Connectors",
    kind: "category",
    body: (
      <>
        <rect x="7.5" y="6.5" width="9" height="11" rx="1" />
        <path d="M10.5 6.5v11M13.5 6.5v11" />
        <path d="M2.5 12h5M16.5 12h5" />
      </>
    ),
  },
};
