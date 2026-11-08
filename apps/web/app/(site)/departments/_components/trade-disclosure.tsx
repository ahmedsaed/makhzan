"use client";

import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A trade's row with its categories folded under a chevron on phones, where
 * the row alone is the list people liked. From `md` there is room, so the
 * categories always show and the chevron goes.
 *
 * The categories are in the server-rendered HTML either way: crawlers and
 * wider screens see them; a phone without JavaScript still has the row's own
 * link to the trade.
 */
export function TradeDisclosure({
  label,
  head,
  children,
}: {
  label: string;
  head: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <div className="flex items-stretch">
        <div className="min-w-0 flex-1">{head}</div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          aria-label={`Categories in ${label}`}
          onClick={() => setOpen((value) => !value)}
          className="grid w-11 shrink-0 place-items-center text-ink-3 hover:text-ink md:hidden"
        >
          <ChevronDown
            aria-hidden="true"
            className={cn("size-5 transition-transform", open && "rotate-180")}
          />
        </button>
      </div>
      <div id={id} data-trade-links className={cn(open ? "block" : "hidden", "md:block")}>
        {children}
      </div>
    </>
  );
}
