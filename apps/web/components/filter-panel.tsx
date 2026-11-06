"use client";

import { SlidersHorizontal, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { chipClass } from "@/components/chips";
import { cn } from "@/lib/utils";

/**
 * The filters beyond the two everyday chips (category, price): a bottom sheet
 * on phones, a side rail from `lg`. The content is the page's, passed as
 * children — typically lists of links, so each choice is a URL.
 *
 * The parts are exported separately because they sit in different places: the
 * sheet's trigger is a chip in the chip bar, the rail is a column beside the
 * results. `FilterPanel` renders both for a page that can put them together.
 */
export function FilterPanel({
  label = "Category, price",
  activeCount = 0,
  children,
}: {
  label?: string;
  activeCount?: number;
  children: React.ReactNode;
}) {
  return (
    <>
      <FilterSheet label={label} activeCount={activeCount}>
        {children}
      </FilterSheet>
      <FilterRail>{children}</FilterRail>
    </>
  );
}

/**
 * A native `<details>`, so the sheet opens with JavaScript off; picking a
 * filter navigates, which is how it closes then. With JavaScript, Escape, the
 * close button and a tap on the backdrop close it too.
 */
export function FilterSheet({
  label = "Category, price",
  activeCount = 0,
  children,
  className,
}: {
  label?: string;
  activeCount?: number;
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && ref.current?.open) ref.current.open = false;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const close = () => {
    if (ref.current) ref.current.open = false;
  };

  return (
    <details ref={ref} className={cn("group lg:hidden", className)}>
      <summary
        className={cn(
          chipClass(activeCount > 0),
          "cursor-pointer list-none [&::-webkit-details-marker]:hidden",
        )}
      >
        <SlidersHorizontal aria-hidden="true" className="size-3.5" />
        {label}
        {activeCount > 0 && <span className="tabular">({activeCount})</span>}
      </summary>
      {/* The scrim is `ink` at low opacity: a token, not a literal (S1). */}
      <div aria-hidden="true" onClick={close} className="fixed inset-0 z-40 bg-ink/40" />
      <div
        role="dialog"
        aria-label={label}
        className="fixed inset-x-0 bottom-0 z-50 flex max-h-[85svh] flex-col rounded-t-card border-t border-line bg-surface"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-2">
          <span className="font-display text-base font-bold text-ink">{label}</span>
          <button
            type="button"
            onClick={close}
            aria-label="Close filters"
            className="-me-2 grid size-11 place-items-center text-ink-2 hover:text-ink"
          >
            <X aria-hidden="true" className="size-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-4 py-4">{children}</div>
      </div>
    </details>
  );
}

/** The desktop side rail. Hidden below `lg`, where the sheet takes over. */
export function FilterRail({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <aside aria-label="Filters" className={cn("hidden lg:block", className)}>
      {children}
    </aside>
  );
}
