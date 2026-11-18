import type { Glyph } from "./types";

/** Security: readers, cameras and safes; each category is the unit a buyer would name. */
export const SECURITY_ICONS: Record<string, Glyph> = {
  // Groups
  "security:access-control": {
    label: "Access Control",
    kind: "group",
    body: (
      <>
        <rect x="6" y="3" width="12" height="18" rx="2" />
        <path d="M10 6h4" />
        <path d="M9.5 10.5h0M12 10.5h0M14.5 10.5h0M9.5 14h0M12 14h0M14.5 14h0M9.5 17.5h0M12 17.5h0M14.5 17.5h0" />
      </>
    ),
  },
  "security:surveillance": {
    label: "Surveillance",
    kind: "group",
    body: (
      <>
        <rect x="3" y="6" width="14" height="7" rx="2" />
        <path d="M17 8l4-1.5v6L17 11" />
        <path d="M9 13v5M5 18.5h8" />
      </>
    ),
  },
  "security:security-equipment": {
    label: "Security Equipment",
    kind: "group",
    body: (
      <>
        <rect x="3.5" y="4" width="17" height="15" rx="2" />
        <circle cx="12" cy="11.5" r="3" />
        <path d="M12 11.5l1.5-1.5M6.5 19v2M17.5 19v2" />
      </>
    ),
  },
  // Access control
  "security:door-access": {
    label: "Door Access",
    kind: "category",
    body: (
      <>
        <path d="M6 21V3.5h12V21M3.5 21h17" />
        <path d="M15 12.5h0M9 7.5h4" />
      </>
    ),
  },
  "security:intercoms": {
    label: "Intercoms",
    kind: "category",
    body: (
      <>
        <rect x="6" y="3" width="12" height="18" rx="2" />
        <circle cx="12" cy="7.25" r="1.5" />
        <path d="M9.5 11.5h5M9.5 14h5" />
        <circle cx="12" cy="18" r="1" />
      </>
    ),
  },
  "security:biometrics": {
    label: "Biometric Readers",
    kind: "category",
    body: (
      <>
        <path d="M4.5 12a7.5 7.5 0 0 1 15 0v3" />
        <path d="M7.5 12.5a4.5 4.5 0 0 1 9 0v2.5c0 2 .5 3.5 1.5 5" />
        <path d="M10.5 14a1.5 1.5 0 0 1 3 0v3c0 1.5.5 2.5 1 3.5M4.5 12v4" />
      </>
    ),
  },
  // Surveillance
  "security:recorders": {
    label: "Recorders",
    kind: "category",
    body: (
      <>
        <rect x="3" y="8" width="18" height="9" rx="2" />
        <path d="M6.5 11.5h6M6.5 14h3M6 17v2M18 17v2" />
        <circle cx="17" cy="12.5" r="1.5" />
      </>
    ),
  },
  "security:remote-controls": {
    label: "Remote Controls",
    kind: "category",
    body: (
      <>
        <rect x="6.5" y="3" width="8" height="18" rx="3" />
        <circle cx="10.5" cy="8.5" r="2" />
        <path d="M8.5 14.5h0M12.5 14.5h0M8.5 17.5h0M12.5 17.5h0" />
        <path d="M17.5 6.5a4 4 0 0 1 0 5M20 4.5a7 7 0 0 1 0 9" />
      </>
    ),
  },
  "security:cash-handling": {
    label: "Cash Handling",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="6.5" width="19" height="11" rx="1.5" />
        <circle cx="12" cy="12" r="2.75" />
        <path d="M6 12h0M18 12h0" />
      </>
    ),
  },
};
