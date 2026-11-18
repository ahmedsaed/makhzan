import { createElement, type ComponentType } from "react";

import { DEPARTMENT_ICONS } from "@/components/category-icon-sets/departments";

/**
 * A line icon per department: what an object tile shows until its photo is curated
 * (lib/content/category-images.ts). Drawn in the category icons' style (24 × 24,
 * 1.5 stroke, round, `currentColor`; docs/DESIGN.md, "Category icons"), neutral on
 * purpose: a stand-in should not look like a product photo.
 */
export type DepartmentGlyph = ComponentType<{ className?: string; strokeWidth?: number }>;

function Svg({ domain, className }: { domain: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      data-department-icon={domain}
      className={className}
    >
      {DEPARTMENT_ICONS[domain]}
    </svg>
  );
}

/** Drawn for an unknown department: a plain box, so a tile never goes without. */
const FALLBACK = (
  <>
    <path d="M12 3 20.5 7.25v9.5L12 21l-8.5-4.25v-9.5z" />
    <path d="m3.5 7.25 8.5 4.25 8.5-4.25M12 11.5V21" />
  </>
);

const COMPONENTS = new Map<string, DepartmentGlyph>(
  Object.keys(DEPARTMENT_ICONS).map((domain) => {
    // The set's own stroke weight stands: a caller's `strokeWidth` was for lucide.
    const Drawn: DepartmentGlyph = ({ className }) => <Svg domain={domain} className={className} />;
    Drawn.displayName = `DepartmentIcon(${domain})`;
    return [domain, Drawn];
  }),
);

const Fallback: DepartmentGlyph = ({ className }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
    className={className}
  >
    {FALLBACK}
  </svg>
);

export function departmentIcon(domain: string): DepartmentGlyph {
  return COMPONENTS.get(domain) ?? Fallback;
}

/** The department's icon as an element, for markup that is not an ObjectTile. */
export function DepartmentIcon({ domain, className }: { domain: string; className?: string }) {
  return createElement(departmentIcon(domain), { className });
}
