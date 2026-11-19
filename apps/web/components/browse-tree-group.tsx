"use client";

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { TREE_CHILDREN } from "@/components/tree-rows";
import { cn } from "@/lib/utils";

/**
 * One group in the browse tree: its link (rendered by the server, `head`), a
 * control that expands or collapses its categories in place, and the
 * categories. The page's own group starts open. With JavaScript off the
 * control does nothing, but the link still leads to the group's page, where
 * it is open.
 *
 * The control's name is fixed, "Subcategories of {group}"; `aria-expanded`
 * alone says whether they are showing.
 *
 * In the phone sheet (the owner's sheet-motion mockup, option A) the link and
 * the control are two separate tinted buttons, 44px each, 8px corners and 6px
 * apart with no divider, so they read as two taps. The control is a funnel,
 * drawn in the category icons' style, and fills solid in `chip-on` while its
 * group is open (150ms). The categories open by grid rows, 0fr to 1fr over
 * 250ms, with nothing measured; closed, they stay in the page (server
 * rendered, crawlable) but `inert`. The desktop sidebar keeps its chevron and
 * shows or hides the categories outright.
 */
export function TreeGroup({
  groupRef,
  name,
  defaultOpen,
  density,
  head,
  children,
}: {
  groupRef: string;
  name: string;
  defaultOpen: boolean;
  density: "sidebar" | "sheet";
  head: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  const sheet = density === "sheet";
  const control = {
    type: "button" as const,
    "aria-expanded": open,
    "aria-controls": id,
    "aria-label": `Subcategories of ${name}`,
    onClick: () => setOpen((was) => !was),
  };

  if (!sheet) {
    return (
      <li data-tree-node={groupRef} data-open={open || undefined}>
        <div className="flex items-center gap-0.5">
          <div className="min-w-0 flex-1">{head}</div>
          <button
            {...control}
            className="grid size-9 shrink-0 place-items-center rounded-md text-ink-3 hover:bg-ground hover:text-ink"
          >
            <ChevronDown
              aria-hidden="true"
              className={cn("size-4 transition-transform", open ? "rotate-0" : "-rotate-90")}
            />
          </button>
        </div>
        <ul id={id} role="list" hidden={!open} className={cn(TREE_CHILDREN, "mt-0.5")}>
          {children}
        </ul>
      </li>
    );
  }

  return (
    <li data-tree-node={groupRef} data-open={open || undefined}>
      <div className="flex items-center gap-1.5">
        <div className="min-w-0 flex-1">{head}</div>
        <button
          {...control}
          data-funnel
          className={cn(
            "grid size-11 shrink-0 place-items-center rounded-md transition-colors duration-150",
            open
              ? "bg-chip-on text-chip-on-ink"
              : "bg-tint text-ink-2 hover:bg-line hover:text-ink",
          )}
        >
          <Funnel />
        </button>
      </div>
      <div
        id={id}
        data-fold
        className={cn(
          "grid transition-[grid-template-rows] duration-250 ease-[cubic-bezier(0.2,0.8,0.2,1)]",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div inert={!open} className="min-h-0 overflow-hidden">
          <div
            className={cn(
              "transition-opacity",
              open
                ? "opacity-100 delay-50 duration-200 ease-out"
                : "opacity-0 duration-150 ease-in",
            )}
          >
            {/* Padded on every side the fold clips, so a category's focus ring
                (2px, 2px out) is never cut. */}
            <ul
              role="list"
              className="ms-[17px] flex flex-col gap-0.5 border-s border-line py-1 ps-2 pe-1"
            >
              {children}
            </ul>
          </div>
        </div>
      </div>
    </li>
  );
}

/**
 * A funnel on the 24 grid, one 1.5 stroke, round caps and joins, no fill,
 * `currentColor`: the category icons' style (docs/DESIGN.md, S7).
 */
export function Funnel() {
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
      data-icon="funnel"
      className="size-[18px]"
    >
      <path d="M3.5 5h17l-6.5 7.5V18l-4 2v-7.5z" />
    </svg>
  );
}
