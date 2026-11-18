"use client";

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * One group in the browse tree: its link (rendered by the server, `head`), a
 * chevron that expands or collapses its categories in place, and the
 * categories. The page's own group starts open. With JavaScript off the
 * chevron does nothing, but the link still leads to the group's page, where
 * it is open.
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
  return (
    <li data-tree-node={groupRef} data-open={open || undefined}>
      <div className="flex items-center gap-0.5">
        <div className="min-w-0 flex-1">{head}</div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          // A fixed name; `aria-expanded` says whether they are showing.
          aria-label={`Subcategories of ${name}`}
          onClick={() => setOpen((was) => !was)}
          className={cn(
            "grid shrink-0 place-items-center rounded-md text-ink-3 hover:bg-ground hover:text-ink",
            density === "sheet" ? "size-11" : "size-9",
          )}
        >
          <ChevronDown
            aria-hidden="true"
            className={cn("size-4 transition-transform", open ? "rotate-0" : "-rotate-90")}
          />
        </button>
      </div>
      <ul
        id={id}
        role="list"
        hidden={!open}
        className="ms-[17px] mt-0.5 flex flex-col gap-0.5 border-s border-line ps-2"
      >
        {children}
      </ul>
    </li>
  );
}
