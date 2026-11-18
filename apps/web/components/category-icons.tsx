import type { ComponentType } from "react";

import { ELECTRICAL_ICONS } from "@/components/category-icon-sets/electrical";
import { MACHINERY_ICONS } from "@/components/category-icon-sets/machinery";
import { SEALS_BEARINGS_ICONS } from "@/components/category-icon-sets/seals-bearings";
import { TOOLS_ICONS } from "@/components/category-icon-sets/tools";
import { CHEMICALS_ICONS } from "@/components/category-icon-sets/chemicals";
import { WELDING_ICONS } from "@/components/category-icon-sets/welding";
import { MATERIALS_ICONS } from "@/components/category-icon-sets/materials";
import { SAFETY_ICONS } from "@/components/category-icon-sets/safety";
import { AUTOMOTIVE_ICONS } from "@/components/category-icon-sets/automotive";
import { TIMBER_ICONS } from "@/components/category-icon-sets/timber";
import { PIPING_ICONS } from "@/components/category-icon-sets/piping";
import { RIGGING_ICONS } from "@/components/category-icon-sets/rigging";
import { SECURITY_ICONS } from "@/components/category-icon-sets/security";
import { GARDEN_ICONS } from "@/components/category-icon-sets/garden";
import { CLEANING_ICONS } from "@/components/category-icon-sets/cleaning";
import { ELECTRONICS_ICONS } from "@/components/category-icon-sets/electronics";
import { PHOTOGRAPHY_ICONS } from "@/components/category-icon-sets/photography";
import type { Glyph, GlyphKind } from "@/components/category-icon-sets/types";
import { departmentIcon } from "@/components/department-icon";

export type { Glyph, GlyphKind };

/**
 * makhzan's own icon set for departments' groups and categories (docs/DESIGN.md,
 * "Category icons"; the owner approved option 3 of the icon pilot, November 2026).
 *
 * The style, which tests/category-icons.test.tsx holds every icon to:
 * - a 24 × 24 grid, drawn inside the 20 × 20 live area a 2-unit margin leaves;
 *   only a category's leads may run on to the edge, as a wire would: a schematic
 *   symbol's, or a hose, cable, pipe stub, port or spray that leaves the object;
 * - one stroke, 1.5 units, with round caps and joins; a dot is a zero-length
 *   segment (`h0`), so it is exactly as heavy as a line;
 * - no fills, and `currentColor`, so an icon takes the colour of its text;
 * - strokes at least 2 units apart, so two lines stay two lines at 18px;
 * - a group is an object you would hold (a board, a motor, a printer), a
 *   category its schematic symbol where electronics has one everyone reads
 *   (resistor, capacitor, diode), else a package or part (a DIP chip, an LED).
 *   The two families then look different at a glance.
 *
 * Keyed by category ref, `domain:slug`, never a bare slug: slugs repeat across
 * departments ("tools:measurement" is not "electronics:measurement"). A group
 * is a top-level category, so its key is its ref too.
 *
 * Shown in the department pages' browse tree (components/browse-tree.tsx), one
 * file per department in components/category-icon-sets/. Every department with
 * a profile has a drawn set (the tests fail for a new one that has none), and
 * a group's tile falls back to the department's line icon
 * (components/department-icon.tsx) only for a ref with no drawing. A category
 * added to a department later shows plain until its icon is added there;
 * tests/category-icons.test.tsx fails until then, so it cannot be forgotten.
 * The same test fails for an icon whose ref no taxonomy has, so none may be
 * drawn ahead of its taxonomy.
 */

export const CATEGORY_ICONS: Readonly<Record<string, Glyph>> = {
  ...ELECTRONICS_ICONS,
  ...PHOTOGRAPHY_ICONS,
  ...ELECTRICAL_ICONS,
  ...TOOLS_ICONS,
  ...CLEANING_ICONS,
  ...GARDEN_ICONS,
  ...SECURITY_ICONS,
  ...RIGGING_ICONS,
  ...PIPING_ICONS,
  ...TIMBER_ICONS,
  ...AUTOMOTIVE_ICONS,
  ...SAFETY_ICONS,
  ...MATERIALS_ICONS,
  ...WELDING_ICONS,
  ...CHEMICALS_ICONS,
  ...MACHINERY_ICONS,
  ...SEALS_BEARINGS_ICONS,
};

/** Departments whose groups and categories are drawn. */
export const DEPARTMENTS_WITH_ICONS: ReadonlySet<string> = new Set(
  Object.keys(CATEGORY_ICONS).map((ref) => ref.slice(0, ref.indexOf(":"))),
);

/** Whether a department's categories carry icons. */
export function hasCategoryIcons(domain: string): boolean {
  return DEPARTMENTS_WITH_ICONS.has(domain);
}

/** The drawn icon for a category or group ref, or null. A bare slug never matches. */
export function categoryGlyph(ref: string): Glyph | null {
  return Object.hasOwn(CATEGORY_ICONS, ref) ? CATEGORY_ICONS[ref] : null;
}

/**
 * A category's icon as an inline `<svg>`, or nothing when it is not drawn.
 * Decorative: the name beside it says the same, so it is hidden from
 * assistive technology.
 */
export function CategoryIcon({ iconRef, className }: { iconRef: string; className?: string }) {
  const glyph = categoryGlyph(iconRef);
  if (!glyph) return null;
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
      data-icon={iconRef}
      className={className}
    >
      {glyph.body}
    </svg>
  );
}

/** A group's icon: one of the drawn category icons, or the department's tile icon. */
export type TileIcon = ComponentType<{ className?: string; strokeWidth?: number }>;

const TILE_ICONS = new Map<string, TileIcon>(
  Object.keys(CATEGORY_ICONS).map((ref) => {
    // The set's own stroke weight stands: a caller's `strokeWidth` is ignored.
    const Drawn: TileIcon = ({ className }) => <CategoryIcon iconRef={ref} className={className} />;
    Drawn.displayName = `CategoryIcon(${ref})`;
    return [ref, Drawn];
  }),
);

/**
 * A group's icon in the browse tree: the drawn one, else the department's line
 * icon, so a group row never goes without one.
 */
export function tileIcon(ref: string, domain: string): TileIcon {
  return TILE_ICONS.get(ref) ?? departmentIcon(domain);
}
