import type { Glyph } from "./types";

/** Chemicals: the container each product comes in for groups, what it does for categories. */
export const CHEMICALS_ICONS: Record<string, Glyph> = {
  // Groups
  "chemicals:adhesives": {
    label: "Adhesives",
    kind: "group",
    body: (
      <>
        <path d="M10.75 2.5h2.5l.75 3h-4z" />
        <rect x="7" y="8.5" width="10" height="12.5" rx="2" />
        <path d="M10 5.5v3M14 5.5v3M7 13.5h10" />
      </>
    ),
  },
  "chemicals:lubricants": {
    label: "Lubricants",
    kind: "group",
    body: (
      <>
        <rect x="5.5" y="3.5" width="13" height="17" rx="2" />
        <path d="M5.5 8h13M5.5 16h13" />
        <path d="M10 5.75h4" />
      </>
    ),
  },
  "chemicals:coatings": {
    label: "Paints & Coatings",
    kind: "group",
    body: (
      <>
        <rect x="5" y="9" width="14" height="12" rx="1.5" />
        <path d="M5 9a7 6 0 0 1 14 0" />
        <path d="M3.5 9h17" />
      </>
    ),
  },
  "chemicals:sealants-fillers": {
    label: "Sealants & Fillers",
    kind: "group",
    body: (
      <>
        <rect x="8" y="9" width="8" height="12" rx="1" />
        <path d="M8 9l2.5-3.5h3L16 9" />
        <path d="M12 5.5v-3M8 18h8" />
      </>
    ),
  },
  "chemicals:maintenance-chemicals": {
    label: "Maintenance Chemicals",
    kind: "group",
    body: (
      <>
        <rect x="6" y="11" width="9" height="10" rx="2" />
        <path d="M8.5 11V7.5H15l2-1.25" />
        <path d="M15 9.5l1.5 2.5-1.5.5" />
        <path d="M20.5 8.5h0M20.5 11.5h0" />
      </>
    ),
  },
  // Adhesives
  "chemicals:industrial-adhesives": {
    label: "Industrial Adhesives",
    kind: "category",
    body: (
      <>
        <rect x="3" y="4.5" width="18" height="5.5" rx="1" />
        <rect x="3" y="14" width="18" height="5.5" rx="1" />
        <path d="M7 12h0M12 12h0M17 12h0" />
      </>
    ),
  },
  "chemicals:instant-adhesives": {
    label: "Instant Adhesives",
    kind: "category",
    body: (
      <>
        <path d="M12 3c-3.5 4-6 7-6 10a6 6 0 0 0 12 0c0-3-2.5-6-6-10z" />
        <path d="M12.75 10.5 10.5 14h3l-2 3.25" />
      </>
    ),
  },
  "chemicals:construction-adhesives": {
    label: "Construction Adhesives",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="1" />
        <path d="M3 9.67h18M3 14.33h18M9 5v4.67M15 9.67v4.66M9 14.33V19" />
      </>
    ),
  },
  "chemicals:adhesive-tapes": {
    label: "Adhesive Tapes",
    kind: "category",
    body: (
      <>
        <path d="M3.5 7.5 5.25 9 3.5 10.5 5.25 12 3.5 13.5H20.5v-6z" />
        <path d="M20.5 13.5c0 3-2 4.5-5 4.5" />
      </>
    ),
  },
  // Lubricants
  "chemicals:greases": {
    label: "Greases",
    kind: "category",
    body: (
      <>
        <rect x="5" y="4.5" width="14" height="3.5" rx="1" />
        <rect x="6" y="8" width="12" height="12.5" rx="2" />
        <path d="M9.5 14h5" />
      </>
    ),
  },
  "chemicals:oils-fluids": {
    label: "Oils & Fluids",
    kind: "category",
    body: (
      <>
        <path d="M10 2.5h4v3l3 3v12.5H7V8.5l3-3z" />
        <path d="M12 12c-1.5 2-2.5 3-2.5 4.25a2.5 2.5 0 0 0 5 0c0-1.25-1-2.25-2.5-4.25z" />
      </>
    ),
  },
  // Coatings
  "chemicals:spray-paints": {
    label: "Spray Paints",
    kind: "category",
    body: (
      <>
        <rect x="6.5" y="9" width="9" height="12" rx="1.5" />
        <path d="M8.5 9V6.5h5V9M11 6.5V3.5h0" />
        <path d="M18.5 5h0M20.5 8h0M18.5 11h0" />
      </>
    ),
  },
  "chemicals:paints": {
    label: "Paints",
    kind: "category",
    body: (
      <>
        <path d="M21 3 14.5 9.5" />
        <path d="M12.5 8.5l3 3-1.5 1.5-3-3z" />
        <path d="M10.5 13.5C7 13 4.5 15.5 4.5 20c4.5 0 7-2 7-5z" />
      </>
    ),
  },
  // Sealants
  "chemicals:silicone-sealants": {
    label: "Silicone Sealants",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5" width="11" height="7" rx="1" />
        <path d="M14 6.5l4 1.5v2l-4 1.5" />
        <path d="M3 18q1.5-2.25 3 0t3 0 3 0 3 0 3 0 3 0" />
      </>
    ),
  },
  "chemicals:sealants": {
    label: "Sealants",
    kind: "category",
    body: (
      <>
        <path d="M10 6.5H3.5v11H10M14 6.5h6.5v11H14" />
        <path d="M10 6.5c1.3 2 2.7 2 4 0M10 17.5c1.3-2 2.7-2 4 0M10.5 12h3" />
      </>
    ),
  },
  "chemicals:foams": {
    label: "Foams",
    kind: "category",
    body: (
      <>
        <rect x="3" y="9.5" width="7" height="11.5" rx="1.5" />
        <path d="M10 12.5h2.5" />
        <path d="M13 15.5a2.5 2.5 0 0 1 .5-5 3.5 3.5 0 0 1 6.5 1 2.25 2.25 0 0 1 0 4z" />
      </>
    ),
  },
  // Maintenance
  "chemicals:rust-removers": {
    label: "Rust Removers",
    kind: "category",
    body: (
      <>
        <rect x="3" y="6.5" width="4" height="9" rx="0.75" />
        <path d="M7 9h14M7 13h14M11 9v4M14.5 9v4M18 9v4" />
        <path d="M8 19h0M12 20.5h0M16 19h0" />
      </>
    ),
  },
  "chemicals:general-chemicals": {
    label: "General Chemicals",
    kind: "category",
    body: (
      <>
        <path d="M7 3.5v15a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-15M5.5 3.5h13" />
        <path d="M7 11q2.5-2 5 0t5 0" />
        <path d="M10 15.5h0M13.5 17h0" />
      </>
    ),
  },
};
