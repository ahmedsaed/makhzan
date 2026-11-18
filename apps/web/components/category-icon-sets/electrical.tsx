import type { Glyph } from "./types";

/** Electrical: installation gear, drawn as the things on a DIN rail and in a panel. */
export const ELECTRICAL_ICONS: Record<string, Glyph> = {
  // Groups
  "electrical:protection": {
    label: "Protection & Switchgear",
    kind: "group",
    body: (
      <>
        <rect x="3.5" y="5" width="17" height="14" rx="1.5" />
        <rect x="6" y="8.5" width="2.5" height="6" rx="0.5" />
        <rect x="10.75" y="8.5" width="2.5" height="6" rx="0.5" />
        <rect x="15.5" y="8.5" width="2.5" height="6" rx="0.5" />
      </>
    ),
  },
  "electrical:motor-control": {
    label: "Motor Control",
    kind: "group",
    body: (
      <>
        <rect x="3" y="5.5" width="13" height="11" rx="2.5" />
        <path d="M7 8.5v5M10 8.5v5M13 8.5v5" />
        <path d="M16 11h5.5M5.5 16.5v3M13.5 16.5v3M3.5 19.5h12" />
      </>
    ),
  },
  "electrical:switching": {
    label: "Switches",
    kind: "group",
    body: (
      <>
        <rect x="5.5" y="3" width="13" height="18" rx="2" />
        <rect x="9" y="7" width="6" height="10" rx="1" />
        <path d="M9 12h6" />
      </>
    ),
  },
  "electrical:control-signalling": {
    label: "Control & Signalling",
    kind: "group",
    body: (
      <>
        <path d="M7 10a5 5 0 0 1 10 0z" />
        <rect x="5" y="10" width="14" height="4" rx="1" />
        <rect x="8" y="14" width="8" height="6.5" rx="1" />
      </>
    ),
  },
  "electrical:relays-timers": {
    label: "Relays & Timers",
    kind: "group",
    body: (
      <>
        <rect x="4" y="4.5" width="16" height="14" rx="2" />
        <rect x="7.5" y="8" width="9" height="6" rx="0.75" />
        <path d="M8 18.5v3M12 18.5v3M16 18.5v3" />
      </>
    ),
  },
  "electrical:automation": {
    label: "Automation & Control",
    kind: "group",
    body: (
      <>
        <rect x="3" y="3.5" width="18" height="17" rx="1.5" />
        <path d="M6.5 7h0M10 7h0M13.5 7h0M17 7h0" />
        <rect x="6" y="10.5" width="7.5" height="6" rx="0.75" />
        <path d="M17 11.5h0M17 15.5h0" />
      </>
    ),
  },
  "electrical:industrial-sensors": {
    label: "Industrial Sensors",
    kind: "group",
    body: (
      <>
        <path d="M4.5 12h-2" />
        <rect x="4.5" y="8" width="12" height="8" rx="1.5" />
        <path d="M8 8v8M11.5 8v8" />
        <path d="M19.5 9.5a3.5 3.5 0 0 1 0 5" />
      </>
    ),
  },
  "electrical:wiring-distribution": {
    label: "Wiring & Distribution",
    kind: "group",
    body: (
      <>
        <path d="M8.5 2.5v4M15.5 2.5v4" />
        <path d="M5.5 6.5h13v4.5a6.5 6.5 0 0 1-13 0z" />
        <path d="M12 17.5v4" />
      </>
    ),
  },
  "electrical:lighting": {
    label: "Lighting",
    kind: "group",
    body: (
      <>
        <path d="M9 14.5c0-1.7-3.5-3-3.5-6.5a6.5 6.5 0 0 1 13 0c0 3.5-3.5 4.8-3.5 6.5z" />
        <path d="M9 17.5h6M10 20.5h4" />
      </>
    ),
  },
  "electrical:power-quality": {
    label: "Power Supply & Quality",
    kind: "group",
    body: (
      <>
        <rect x="3" y="6" width="18" height="12" rx="2" />
        <path d="M6.5 12q1.75-4 3.5 0t3.5 0 3.5 0" />
      </>
    ),
  },
  // Protection
  "electrical:circuit-breakers": {
    label: "Circuit Breakers",
    kind: "category",
    body: (
      <>
        <path d="M12 0v6M12 19v5" />
        <path d="M12 19l5.5-11.5" />
        <path d="M15 4l5 5M20 4l-5 5" />
      </>
    ),
  },
  "electrical:rcd-elcb": {
    label: "Earth Leakage Protection",
    kind: "category",
    body: (
      <>
        <rect x="5" y="2.5" width="14" height="9" rx="1.5" />
        <path d="M12 5.5v3" />
        <path d="M12 11.5v4.5M7.5 16h9M9.5 18.75h5M11.25 21.5h1.5" />
      </>
    ),
  },
  "electrical:overload-relays": {
    label: "Overload Relays",
    kind: "category",
    body: (
      <>
        <path d="M0 12h4.5M19.5 12H24" />
        <rect x="4.5" y="6.5" width="15" height="11" rx="0.75" />
        <path d="M8 12.5 9.75 9 12 15l2.25-6 1.75 3.5" />
      </>
    ),
  },
  "electrical:disconnectors": {
    label: "Disconnectors & Isolators",
    kind: "category",
    body: (
      <>
        <path d="M12 0v6M12 19v5" />
        <path d="M12 19 18 7.5" />
        <path d="M12.6 12.2l4.8 2.5" />
      </>
    ),
  },
  // Motor control
  "electrical:contactors": {
    label: "Contactors",
    kind: "category",
    body: (
      <>
        <rect x="4.5" y="6.5" width="15" height="11" rx="1.5" />
        <path d="M8 6.5v-4M12 6.5v-4M16 6.5v-4M8 17.5v4M12 17.5v4M16 17.5v4" />
        <rect x="8.5" y="10.5" width="7" height="3" rx="0.5" />
      </>
    ),
  },
  "electrical:motor-starters": {
    label: "Motor Starters",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="7.5" />
        <path d="M12 0v4.5M12 19.5V24" />
        <path d="M8.5 15.5v-7l3.5 4 3.5-4v7" />
      </>
    ),
  },
  "electrical:vfd-soft-start": {
    label: "VFDs & Soft Starters",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="3" width="17" height="18" rx="1.5" />
        <path d="M7 9.5q2-4.5 4 0t4 0" />
        <path d="M7 16h10" />
        <circle cx="14" cy="16" r="1.25" />
      </>
    ),
  },
  // Switching
  "electrical:general-switches": {
    label: "Switches",
    kind: "category",
    body: <path d="M0 15h5.5M5.5 15 17 7.5M18.5 15H24" />,
  },
  "electrical:limit-switches": {
    label: "Limit Switches",
    kind: "category",
    body: (
      <>
        <rect x="3" y="9" width="11" height="12" rx="1.5" />
        <path d="M14 13h5.5V8.5" />
        <circle cx="19.5" cy="6.5" r="2" />
      </>
    ),
  },
  "electrical:process-switches": {
    label: "Pressure, Float & Flow Switches",
    kind: "category",
    body: (
      <>
        <path d="M12 2.5V8" />
        <ellipse cx="12" cy="12" rx="5" ry="4" />
        <path d="M3 20q2.25-2.5 4.5 0t4.5 0 4.5 0 4.5 0" />
      </>
    ),
  },
  // Control & signalling
  "electrical:push-buttons": {
    label: "Push Buttons",
    kind: "category",
    body: (
      <>
        <path d="M0 17h6M18 17h6" />
        <path d="M7 13h10" />
        <path d="M12 13V6M8.5 6h7" />
      </>
    ),
  },
  "electrical:selector-switches": {
    label: "Selector Switches",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="13" r="5.5" />
        <path d="M12 13V8.5" />
        <path d="M4 9h0M12 3.5h0M20 9h0" />
      </>
    ),
  },
  "electrical:pilot-lamps": {
    label: "Pilot Lamps & Indicators",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="3.5" />
        <path d="M18.5 12H21M5.5 12H3M12 5.5V3M12 18.5V21M16.6 7.4l1.8-1.8M16.6 16.6l1.8 1.8M7.4 7.4 5.6 5.6M7.4 16.6l-1.8 1.8" />
      </>
    ),
  },
  "electrical:control-stations": {
    label: "Control Stations",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <circle cx="8" cy="10" r="2" />
        <circle cx="16" cy="10" r="2" />
        <path d="M7 15.5h10" />
      </>
    ),
  },
  // Relays & timers
  "electrical:relays": {
    label: "Relays",
    kind: "category",
    body: (
      <>
        <rect x="3" y="7" width="7" height="10" rx="0.75" />
        <path d="M6.5 0v7M6.5 17v7" />
        <path d="M17.5 0v6M17.5 18v6M17.5 18 21 7.5" />
      </>
    ),
  },
  "electrical:timers": {
    label: "Timers",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="13.5" r="7.5" />
        <path d="M10 3h4M12 3v3" />
        <path d="M12 13.5 15 10.5" />
      </>
    ),
  },
  // Automation
  "electrical:plc": {
    label: "PLCs",
    kind: "category",
    body: (
      <>
        <path d="M4.5 3v18M19.5 3v18" />
        <path d="M4.5 8h5M9.5 5v6M14.5 5v6M14.5 8h5" />
        <path d="M4.5 16h4.5M15 16h4.5" />
        <circle cx="12" cy="16" r="3" />
      </>
    ),
  },
  "electrical:controllers": {
    label: "Process Controllers",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="3.5" width="17" height="17" rx="1.5" />
        <rect x="6.5" y="6.5" width="11" height="4.5" rx="0.5" />
        <path d="M7 16l2-2 2 2M13 14l2 2 2-2" />
      </>
    ),
  },
  "electrical:signal-conditioning": {
    label: "Signal Conditioning",
    kind: "category",
    body: (
      <>
        <rect x="6" y="5" width="12" height="14" rx="1" />
        <path d="M0 9h6M0 15h6M18 12h6" />
        <path d="M8.5 12q1.5-3.5 3 0t3 0" />
      </>
    ),
  },
  // Industrial sensors
  "electrical:inductive-sensors": {
    label: "Inductive & Proximity Sensors",
    kind: "category",
    body: (
      <>
        <path d="M3 12a2 2 0 0 1 4 0 2 2 0 0 1 4 0" />
        <path d="M13.5 8.5a4.5 4.5 0 0 1 0 7" />
        <rect x="17" y="5.5" width="3.5" height="13" rx="0.75" />
      </>
    ),
  },
  "electrical:photoelectric-sensors": {
    label: "Photoelectric Sensors",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="8" width="5" height="8" rx="1" />
        <rect x="16.5" y="8" width="5" height="8" rx="1" />
        <path d="M10.5 12h0M13.5 12h0" />
      </>
    ),
  },
  "electrical:capacitive-sensors": {
    label: "Capacitive Sensors",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="9.5" width="6" height="5" rx="1" />
        <rect x="12" y="3" width="9.5" height="18" rx="1.5" />
        <path d="M12 12h9.5" />
      </>
    ),
  },
  "electrical:motion-sensors": {
    label: "Motion Sensors",
    kind: "category",
    body: (
      <>
        <path d="M4 19a8 8 0 0 1 16 0z" />
        <path d="M8 7.5a5.5 5.5 0 0 1 8 0" />
        <path d="M12 12.5v3" />
      </>
    ),
  },
  "electrical:process-sensors": {
    label: "Pressure & Process Sensors",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="10" r="7.5" />
        <path d="M12 10l3.5-3.5" />
        <rect x="10" y="17.5" width="4" height="4" rx="0.5" />
      </>
    ),
  },
  "electrical:sensor-accessories": {
    label: "Sensor Accessories",
    kind: "category",
    body: (
      <>
        <path d="M2.5 12H9" />
        <rect x="9" y="7.5" width="5" height="9" rx="1" />
        <rect x="14" y="9.5" width="4" height="5" rx="0.5" />
        <path d="M18 11h3.5M18 13h3.5" />
      </>
    ),
  },
  // Wiring & distribution
  "electrical:sockets-plugs": {
    label: "Sockets & Plugs",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="3.5" width="17" height="17" rx="3.5" />
        <circle cx="12" cy="12" r="5.5" />
        <path d="M9.5 12h0M14.5 12h0" />
      </>
    ),
  },
  "electrical:terminal-blocks": {
    label: "Terminal Blocks",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5.5" width="18" height="11" rx="1.5" />
        <path d="M9 5.5v11M15 5.5v11" />
        <path d="M6 10h0M12 10h0M18 10h0" />
        <path d="M6 16.5v4M12 16.5v4M18 16.5v4" />
      </>
    ),
  },
  "electrical:junctions": {
    label: "Junctions & Connectors",
    kind: "category",
    body: (
      <>
        <rect x="7" y="7.5" width="10" height="9" rx="1.5" />
        <path d="M2 9.5h5M2 14.5h5M17 12h5" />
      </>
    ),
  },
  "electrical:enclosures": {
    label: "Panels & Enclosures",
    kind: "category",
    body: (
      <>
        <rect x="4" y="2.5" width="16" height="19" rx="1.5" />
        <rect x="7" y="5.5" width="10" height="13" rx="0.5" />
        <path d="M14.5 12h0" />
      </>
    ),
  },
  "electrical:cable-management": {
    label: "Cable Management",
    kind: "category",
    body: (
      <>
        <path d="M3 7.5h18M3 16.5h18" />
        <path d="M6.5 7.5v9M12 7.5v9M17.5 7.5v9" />
      </>
    ),
  },
  // Lighting
  "electrical:lamps": {
    label: "Lamps & Bulbs",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="6" />
        <path d="M7.76 7.76l8.48 8.48M16.24 7.76l-8.48 8.48" />
        <path d="M0 12h6M18 12h6" />
      </>
    ),
  },
  "electrical:floodlights": {
    label: "Floodlights",
    kind: "category",
    body: (
      <>
        <rect x="3.5" y="5.5" width="11" height="9" rx="1.5" />
        <path d="M17.5 8h4M17.5 11h4M17.5 14h4" />
        <path d="M9 14.5v6.5M5.5 21h7" />
      </>
    ),
  },
  "electrical:emergency-lighting": {
    label: "Emergency Lighting",
    kind: "category",
    body: (
      <>
        <rect x="2.5" y="6.5" width="19" height="11" rx="1.5" />
        <path d="M6.5 12h11M14 8.5l3.5 3.5-3.5 3.5" />
      </>
    ),
  },
  // Power supply & quality
  "electrical:ups": {
    label: "UPS",
    kind: "category",
    body: (
      <>
        <rect x="5.5" y="3" width="13" height="16" rx="2" />
        <path d="M12.75 7.5 9.75 12h4.5l-3 4.5" />
        <path d="M8 19v2.5M16 19v2.5" />
      </>
    ),
  },
  "electrical:power-supplies": {
    label: "Power Supplies",
    kind: "category",
    body: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="1" />
        <path d="M3 19 21 5" />
        <path d="M5.5 9q1.25-2.5 2.5 0t2.5 0" />
        <path d="M13.5 15h4M13.5 17.5h4" />
      </>
    ),
  },
  "electrical:stabilizers": {
    label: "Stabilizers & PF Correction",
    kind: "category",
    body: (
      <>
        <path d="M7 2.5V4a2.5 2.5 0 0 1 0 5 2.5 2.5 0 0 1 0 5 2.5 2.5 0 0 1 0 5v1.5" />
        <path d="M17 2.5V4a2.5 2.5 0 0 0 0 5 2.5 2.5 0 0 0 0 5 2.5 2.5 0 0 0 0 5v1.5" />
        <path d="M12 3v18" />
      </>
    ),
  },
  "electrical:energy-meters": {
    label: "Energy Meters",
    kind: "category",
    body: (
      <>
        <circle cx="12" cy="12" r="9" />
        <rect x="8" y="7.5" width="8" height="4" rx="0.5" />
        <path d="M9 16h0M12 16h0M15 16h0" />
      </>
    ),
  },
};
