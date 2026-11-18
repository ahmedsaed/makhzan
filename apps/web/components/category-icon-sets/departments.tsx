import type { ReactElement } from "react";

/**
 * One drawn icon per department, for its tile and list rows: the same 24 × 24,
 * 1.5-stroke style as the category icons, one object that stands for the trade.
 * Keyed by the department's domain.
 */
export const DEPARTMENT_ICONS: Readonly<Record<string, ReactElement>> = {
  automotive: (
    <>
      <path d="M5.25 17H2.5v-4.5l2.3-4.2A2 2 0 0 1 6.5 7.5h7.2a2 2 0 0 1 1.5.7l3.3 3.8 2 .7V17h-2.75M9.75 17h4.5" />
      <circle cx="7.5" cy="17" r="2.25" />
      <circle cx="16.5" cy="17" r="2.25" />
      <path d="M10.5 7.5V12" />
    </>
  ),
  chemicals: (
    <>
      <path d="M9.5 3h5M10.5 3v6L5 18.5A1.5 1.5 0 0 0 6.3 21h11.4a1.5 1.5 0 0 0 1.3-2.5L13.5 9V3" />
      <path d="M7.5 15h9" />
    </>
  ),
  cleaning: (
    <>
      <rect x="6" y="10" width="9" height="11.5" rx="2" />
      <rect x="8" y="6" width="4" height="4" />
      <path d="M8 6V3.5h8l1.5 2.5" />
      <path d="M20.5 5.5h0M20.5 9h0M18 8h0" />
    </>
  ),
  electrical: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M13 6.5 8.5 12.75H12L11 17.5l4.5-6.25h-3.25z" />
    </>
  ),
  electronics: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="1.5" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="0.5" />
      <path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3" />
    </>
  ),
  garden: (
    <>
      <path d="M6.5 14h11l-1.5 7H8z" />
      <path d="M12 14V8" />
      <path d="M12 10c0-3-2.5-4.5-5.5-4.5 0 3 2 4.5 5.5 4.5z" />
      <path d="M12 8c0-2.5 2-4 4.5-4 0 2.5-1.5 4-4.5 4z" />
    </>
  ),
  machinery: (
    <>
      <path d="M19.2 12L21.41 13.34L20.78 15.64L18.2 15.67L17.09 17.09L17.7 19.6L15.64 20.78L13.79 18.97L12 19.2L10.66 21.41L8.36 20.78L8.33 18.2L6.91 17.09L4.4 17.7L3.22 15.64L5.03 13.79L4.8 12L2.59 10.66L3.22 8.36L5.8 8.33L6.91 6.91L6.3 4.4L8.36 3.22L10.21 5.03L12 4.8L13.34 2.59L15.64 3.22L15.67 5.8L17.09 6.91L19.6 6.3L20.78 8.36L18.97 10.21Z" />
      <path d="M12 9l2.6 1.5v3L12 15l-2.6-1.5v-3z" />
    </>
  ),
  materials: <path d="M4 3.5h16V7h-6.5v10H20v3.5H4V17h6.5V7H4z" />,
  photography: (
    <>
      <path d="M4.5 7h3l1.5-2.5h6L16.5 7h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" />
      <circle cx="12" cy="13" r="3.5" />
    </>
  ),
  piping: (
    <>
      <path d="M2.5 6.5h11A5.5 5.5 0 0 1 19 12v9.25" />
      <path d="M2.5 12.5h7.5a3 3 0 0 1 3 3v5.75" />
      <path d="M5 4.5v10M10.5 21.25H21.5" />
    </>
  ),
  rigging: (
    <>
      <circle cx="13" cy="5" r="2.5" />
      <path d="M13 7.5v8a4.5 4.5 0 0 1-9 0V13" />
    </>
  ),
  safety: (
    <>
      <path d="M5 15.5V14a7 7 0 0 1 14 0v1.5" />
      <rect x="3" y="15.5" width="18" height="4" rx="1.5" />
      <path d="M9.5 8v7.5M14.5 8v7.5" />
    </>
  ),
  "seals-bearings": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 6.5h0M16.76 9.25h0M16.76 14.75h0M12 17.5h0M7.24 14.75h0M7.24 9.25h0" />
    </>
  ),
  security: (
    <>
      <rect x="5" y="10.5" width="14" height="10.5" rx="2" />
      <path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" />
      <path d="M12 14.5v3" />
    </>
  ),
  timber: (
    <>
      <ellipse cx="5.5" cy="12" rx="3.5" ry="7" />
      <ellipse cx="5.5" cy="12" rx="1.25" ry="3" />
      <path d="M5.5 5H18M5.5 19H18" />
      <path d="M18 5a3.5 7 0 0 1 0 14" />
    </>
  ),
  tools: (
    <path d="M9.17 11.29L5.64 12L3.16 9.53L3.16 7.4L4.22 6.34L7.4 9.53L9.53 7.4L6.34 4.22L7.4 3.16L9.53 3.16L12 5.64L11.29 9.17L16.6 14.47L18.72 14.47L19.78 15.54L19.78 17.66L17.66 19.78L15.54 19.78L14.47 18.72L14.47 16.6Z" />
  ),
  welding: (
    <>
      <path d="M5 11a7 7 0 0 1 14 0v7a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3z" />
      <rect x="8" y="11" width="8" height="3.5" rx="0.75" />
    </>
  ),
};
