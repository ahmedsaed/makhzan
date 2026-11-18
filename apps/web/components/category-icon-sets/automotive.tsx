import type { Glyph } from "./types";

/** Automotive: workshop equipment and vehicle consumables. */
export const AUTOMOTIVE_ICONS: Record<string, Glyph> = {
  // Groups
  "automotive:vehicle-diagnostics": {
    label: "Diagnostics",
    kind: "group",
    body: (
      <>
        <rect x="6" y="3" width="12" height="18" rx="2" />
        <rect x="8.5" y="5.5" width="7" height="5" rx="0.5" />
        <path d="M9 14h0M12 14h0M15 14h0M9 17.5h0M12 17.5h0M15 17.5h0" />
      </>
    ),
  },
  "automotive:vehicle-service": {
    label: "Servicing Equipment",
    kind: "group",
    body: (
      <>
        <path d="M4.5 3v18M19.5 3v18M2.5 21h19" />
        <rect x="8" y="8" width="8" height="4" rx="1.5" />
        <path d="M4.5 14.5h15" />
      </>
    ),
  },
  "automotive:vehicle-accessories": {
    label: "Accessories & Consumables",
    kind: "group",
    body: (
      <>
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="2.5" />
        <path d="M3.5 12H9.5M14.5 12h6M12 14.5V20.5" />
      </>
    ),
  },
  // Diagnostics
  "automotive:battery-testers": {
    label: "Battery & Alternator Testers",
    kind: "category",
    body: (
      <>
        <rect x="3" y="9" width="18" height="11" rx="1.5" />
        <path d="M7 9V6.5h2V9M15 9V6.5h2V9" />
        <path d="M7.5 14.5h3M9 13v3M14 14.5h3" />
      </>
    ),
  },
  "automotive:electrical-testers": {
    label: "Electrical Testers",
    kind: "category",
    body: (
      <>
        <rect x="9" y="3" width="6" height="10" rx="2" />
        <path d="M12 13v5" />
        <path d="M15 6h3a3 3 0 0 1 3 3v8h2" />
      </>
    ),
  },
  // Service
  "automotive:alignment": {
    label: "Alignment Equipment",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="14.5" r="4.5" />
        <path d="M12 14.5h0M5.5 10.5a7.5 7.5 0 0 1 13 0" />
        <path d="M5.5 10.5 8 10M5.5 10 5 7.5M18.5 10 16 10M18.5 10l.5-2.5" />
      </>
    ),
  },
  "automotive:oil-service": {
    label: "Oil & Fluid Service",
    kind: "category",
    body: (
      <>
        <path d="M3.5 15h17l-2 5h-13z" />
        <path d="M12 3c-1.5 2-2.5 3-2.5 4.5a2.5 2.5 0 0 0 5 0c0-1.5-1-2.5-2.5-4.5z" />
        <path d="M12 11.5V13" />
      </>
    ),
  },
  "automotive:body-shop": {
    label: "Body Shop Equipment",
    kind: "category",
    body: (
      <>
        <rect x="7" y="3" width="6" height="5" rx="2" />
        <path d="M10 8v2.5" />
        <rect x="3.5" y="10.5" width="13" height="4" rx="2" />
        <path d="M7.5 14.5 6.5 21H10l1-6.5M16.5 12.5H19M20.5 10h0M21.5 12.5h0M20.5 15h0" />
      </>
    ),
  },
  "automotive:vehicle-cleaning": {
    label: "Vehicle Cleaning Equipment",
    kind: "category",
    body: (
      <>
        <rect x="4" y="11" width="16" height="9" rx="3" />
        <path d="M8 15.5h0M12 14h0M16 16h0" />
        <circle cx="8" cy="6" r="1.5" />
        <circle cx="14" cy="5.5" r="2.25" />
      </>
    ),
  },
  // Accessories
  "automotive:booster-cables": {
    label: "Booster Cables",
    kind: "category",
    body: (
      <>
        <path d="M3 4.5h6.5l2 2.5-2 2.5H3z" />
        <path d="M3 14.5h6.5l2 2.5-2 2.5H3z" />
        <path d="M11.5 7h3a4.5 4.5 0 0 1 0 10h-3" />
      </>
    ),
  },
  "automotive:tie-downs": {
    label: "Tie-Downs",
    kind: "category",
    body: (
      <>
        <rect x="8" y="7.5" width="8" height="9" rx="1.5" />
        <path d="M10.5 7.5V4.5h3v3" />
        <path d="M2.5 10.5H8M16 10.5h5.5M2.5 13.5H8M16 13.5h5.5" />
      </>
    ),
  },
  "automotive:car-care": {
    label: "Car Care",
    kind: "category",
    body: (
      <>
        <path d="M11 3.5l1.9 5.6 5.6 1.9-5.6 1.9L11 18.5l-1.9-5.6L3.5 11l5.6-1.9z" />
        <path d="M19 15.5l.75 2.25L22 18.5l-2.25.75L19 21.5l-.75-2.25L16 18.5l2.25-.75z" />
      </>
    ),
  },
  "automotive:belts": {
    label: "Belts",
    kind: "category",
    body: (
      <>
        <circle cx="6.5" cy="12" r="4" />
        <circle cx="17" cy="12" r="3" />
        <path d="M6.5 8 17 9M6.5 16 17 15" />
      </>
    ),
  },
};
