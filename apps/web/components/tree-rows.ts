import { cn } from "@/lib/utils";

/**
 * The rows of the department pages' browse tree (components/browse-tree.tsx)
 * and of the search filters' category list (components/results-filters.tsx),
 * in one place so the two cannot drift apart (docs/DESIGN.md, layout B).
 *
 * `sidebar`: plain 36px rows for a pointer, inside a bordered panel.
 * `sheet`: 44px tinted buttons for a finger (S4), the owner's sheet-motion
 * mockup, option A. Counts on the tint are ink-2: ink-3 falls short of 4.5:1
 * on the light tint (S2).
 */
export type TreeDensity = "sidebar" | "sheet";

export function treeRow(density: TreeDensity): string {
  return cn(
    "flex w-full items-center gap-2.5 px-2.5 text-ink",
    density === "sheet"
      ? "min-h-11 rounded-md bg-tint text-[15px] transition-colors duration-150 hover:bg-line"
      : "min-h-9 rounded-md py-1 text-sm hover:bg-ground",
  );
}

/**
 * The place you are, or the filter in force: a 2px outline, never a fill. Its
 * outline would hide the keyboard's focus ring (the same property), so under
 * focus it becomes the site's ring instead: the link colour, 2px out.
 */
export const TREE_CURRENT =
  "font-semibold outline-2 -outline-offset-2 outline-chip-on focus-visible:outline-link focus-visible:outline-offset-2";

export function treeCount(density: TreeDensity): string {
  return cn(
    "ms-auto shrink-0 ps-2 text-[13px] font-normal tabular",
    density === "sheet" ? "text-ink-2" : "text-ink-3",
  );
}

/** The bordered panel the sidebar's rows sit in. */
export const TREE_PANEL = "rounded-card border border-line bg-surface p-1.5";

/** The small capitals label above a panel ("Browse Electronics", "Category"). */
export const TREE_LABEL =
  "px-2.5 pt-2 pb-2 text-xs font-semibold tracking-[0.06em] text-ink-2 uppercase";

/** A group's children, indented under it with a hairline on their start side. */
export const TREE_CHILDREN = "ms-[17px] flex flex-col gap-0.5 border-s border-line ps-2";
