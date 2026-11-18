import type { Glyph } from "./types";

/** Welding: machines and cylinders for groups, the torch, rod or clamp itself for categories. */
export const WELDING_ICONS: Record<string, Glyph> = {
  // Groups
  "welding:welding-equipment": {
    label: "Welding & Cutting Machines",
    kind: "group",
    body: (
      <>
        <rect x="3" y="6" width="14" height="13" rx="2" />
        <path d="M7 6V4h6v2" />
        <circle cx="8" cy="12.5" r="2" />
        <path d="M12.5 11h2M12.5 14h2" />
        <path d="M17 10h2.5a2 2 0 0 1 2 2v7" />
      </>
    ),
  },
  "welding:torch-consumables": {
    label: "Torches & Consumables",
    kind: "group",
    body: (
      <>
        <path d="M8 21V9.5a4 4 0 0 1 8 0V21z" />
        <path d="M12 5.5V3M10 3h4M8 14h8" />
      </>
    ),
  },
  "welding:welding-accessories": {
    label: "Accessories",
    kind: "group",
    body: (
      <>
        <rect x="3" y="5" width="15" height="4" rx="2" />
        <rect x="5" y="9" width="11" height="3" />
        <path d="M6.5 12v4M9 12v4M11.5 12v4M14 12v4" />
        <path d="M18 7h3.5" />
      </>
    ),
  },
  // Machines
  "welding:welding-machines": {
    label: "Welding Machines",
    kind: "category",
    body: (
      <>
        <path d="M4 4l7 9" />
        <path d="M3 18h18M8 21h8" />
        <path d="M15 8V5M18 11h3M15.5 11.5l2.25-2.25" />
      </>
    ),
  },
  "welding:cutting-machines": {
    label: "Cutting Machines",
    kind: "category",
    body: (
      <>
        <rect x="10" y="3" width="4" height="6" rx="0.75" />
        <path d="M10 9l1 3h2l1-3" />
        <path d="M2.5 16h8.5M13 16h8.5" />
        <path d="M9 20h0M12 21h0M15 20h0" />
      </>
    ),
  },
  // Torches
  "welding:welding-torches": {
    label: "Welding Torches",
    kind: "category",
    body: (
      <>
        <rect x="3" y="9.5" width="7.5" height="5" rx="2" />
        <path d="M10.5 12h3.5a4.5 4.5 0 0 0 4.5-4.5V6" />
        <rect x="16" y="2.75" width="5" height="3.25" rx="0.75" />
        <path d="M3 12H0.5" />
      </>
    ),
  },
  "welding:cutting-torches": {
    label: "Cutting Torches",
    kind: "category",
    body: (
      <>
        <rect x="3" y="11" width="10" height="4" rx="2" />
        <path d="M13 13h5M18 13V7M16 7h4" />
        <path d="M6 11V8M10 11V8M5 8h2M9 8h2" />
        <path d="M18 4.5h0" />
      </>
    ),
  },
  "welding:torch-parts": {
    label: "Torch Parts",
    kind: "category",
    body: (
      <>
        <path d="M9 3.5h6l1.5 7h-9z" />
        <path d="M10.5 13.5v4l1.5 3 1.5-3v-4" />
      </>
    ),
  },
  // Accessories
  "welding:electrodes": {
    label: "Electrodes & Rods",
    kind: "category",
    body: (
      <>
        <rect x="9.5" y="3" width="5" height="14" rx="1" />
        <path d="M12 17v4.5M9.5 7.5h5" />
      </>
    ),
  },
  "welding:electrode-holders": {
    label: "Electrode Holders",
    kind: "category",
    body: (
      <>
        <rect x="3" y="9" width="10" height="6" rx="3" />
        <path d="M13 10.5h4.5l3.5-3M13 13.5h4.5l3.5 3" />
        <path d="M17.5 12H22" />
      </>
    ),
  },
  "welding:earth-clamps": {
    label: "Earth Clamps",
    kind: "category",
    body: (
      <>
        <path d="M3 6.5h12l5.5 4.5H3z" />
        <path d="M3 17.5h12l5.5-4.5H3z" />
        <path d="M7 11v2M10 11v2" />
      </>
    ),
  },
  "welding:gas-regulators": {
    label: "Gas Regulators",
    kind: "category",
    body: (
      <>
        <circle cx="7.5" cy="6" r="2.5" />
        <circle cx="16.5" cy="6" r="2.5" />
        <path d="M7.5 8.5V10M16.5 8.5V10" />
        <rect x="5" y="10" width="14" height="5" rx="1.5" />
        <path d="M12 15v4.5M10 19.5h4M19 12.5h2.5M5 12.5H2.5" />
      </>
    ),
  },
  "welding:flashback-arrestors": {
    label: "Flashback Arrestors",
    kind: "category",
    body: (
      <>
        <rect x="6" y="6.5" width="12" height="11" rx="2" />
        <path d="M2.5 12H6M18 12h3.5" />
        <path d="M9 9.5v5l4-2.5zM15.5 9.5v5" />
      </>
    ),
  },
  "welding:welding-magnets": {
    label: "Welding Magnets",
    kind: "category",
    body: <path d="M5.5 3.5v9.5a6.5 6.5 0 0 0 13 0V3.5h-4V13a2.5 2.5 0 0 1-5 0V3.5z" />,
  },
  "welding:rod-heaters": {
    label: "Rod Heaters & Ovens",
    kind: "category",
    body: (
      <>
        <rect x="4" y="3.5" width="16" height="17" rx="2" />
        <path d="M7.5 12.5h9M7.5 16h9" />
        <path d="M8 7h0M12 7h0M16 7h0" />
      </>
    ),
  },
  "welding:torch-heaters": {
    label: "Heating Torches",
    kind: "category",
    body: (
      <>
        <rect x="3" y="13" width="6" height="8" rx="1.5" />
        <path d="M9 16.5h4.5v-4" />
        <path d="M13.5 2.5c-2.5 2.5-3.75 4-3.75 6a3.75 3.75 0 0 0 7.5 0c0-2-1.25-3.5-3.75-6z" />
      </>
    ),
  },
  "welding:torch-lighters": {
    label: "Torch Lighters",
    kind: "category",
    body: (
      <>
        <rect x="7" y="10" width="9" height="11" rx="2" />
        <path d="M7 13.5h9M9 10V7.5h5V10" />
        <path d="M11.5 2.5c-1.25 1.25-1.75 2.25-1.75 3a1.75 1.75 0 0 0 3.5 0c0-.75-.5-1.75-1.75-3z" />
      </>
    ),
  },
  "welding:chipping-hammers": {
    label: "Chipping Hammers",
    kind: "category",
    body: (
      <>
        <path d="M2.5 4.5 7.5 6h9l5-1.5v4l-5 1.5h-9l-5-1.5z" />
        <rect x="10.5" y="10" width="3" height="11.5" rx="1" />
      </>
    ),
  },
};
