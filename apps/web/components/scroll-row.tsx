"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A row of links that, on a phone, is one line scrolling sideways inside
 * itself (the owner's decision of 2026-11-18: wrapped group tiles and category
 * chips pushed the products a long way down). From `sm` it is whatever layout
 * `className` gives it; the phone row is PHONE_ROW, all `max-sm:`,
 * so tablet and desktop are untouched. (It stays in this module: a constant
 * exported from a client module reaches a server component as a reference, not a string.)
 *
 * A plain `overflow-x-auto` already scrolls with momentum, and works with
 * JavaScript off. On top of it:
 * - the selected link (`aria-current`) is scrolled into view on load, without
 *   moving the page;
 * - a link that takes keyboard focus is brought clear of the edges;
 * - three cues that there is more: the next item shows partly, the edge with
 *   hidden content fades (globals.css, `data-more-start` / `data-more-end`),
 *   and a small chevron sits on that edge, gone once the row reaches its end.
 *   A tap on it scrolls about one screen. The chevrons are pointer helpers
 *   only (`aria-hidden`, out of the tab order): the links themselves are the
 *   list, reachable by keyboard and screen reader, and focus scrolls them in.
 * - no animation under `prefers-reduced-motion`: every scroll is instant.
 */
export function ScrollRow({
  label,
  className,
  style,
  children,
}: {
  label: string;
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  const [more, setMore] = useState({ start: false, end: false });

  const scrollTo = useCallback((left: number, smooth: boolean) => {
    const row = ref.current;
    if (!row) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    row.scrollTo({ left, behavior: smooth && !reduce ? "smooth" : "auto" });
  }, []);

  useEffect(() => {
    const row = ref.current;
    if (!row) return;
    const centre = (item: HTMLElement, smooth: boolean) =>
      scrollTo(item.offsetLeft - (row.clientWidth - item.offsetWidth) / 2, smooth);
    const measure = () => {
      const scrolls = row.scrollWidth > row.clientWidth + 1;
      const start = scrolls && row.scrollLeft > 1;
      const end = scrolls && row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
      setMore((was) => (was.start === start && was.end === end ? was : { start, end }));
    };

    const current = row.querySelector<HTMLElement>("[aria-current]");
    if (current && row.scrollWidth > row.clientWidth + 1) centre(current, false);
    measure();

    const onFocus = (event: FocusEvent) => {
      const item = (event.target as HTMLElement).closest<HTMLElement>("a");
      if (!item || !row.contains(item)) return;
      const box = item.getBoundingClientRect();
      const frame = row.getBoundingClientRect();
      // Clear of the fade and the chevron (44px) on either side, or centred.
      if (box.left < frame.left + 44 || box.right > frame.right - 44) centre(item, true);
    };
    row.addEventListener("scroll", measure, { passive: true });
    row.addEventListener("focusin", onFocus);
    window.addEventListener("resize", measure);
    return () => {
      row.removeEventListener("scroll", measure);
      row.removeEventListener("focusin", onFocus);
      window.removeEventListener("resize", measure);
    };
  }, [scrollTo]);

  const page = (direction: 1 | -1) => {
    const row = ref.current;
    if (row) scrollTo(row.scrollLeft + direction * row.clientWidth * 0.8, true);
  };

  return (
    <div className="relative">
      <nav
        ref={ref}
        aria-label={label}
        data-scroll-row
        data-more-start={more.start || undefined}
        data-more-end={more.end || undefined}
        style={style}
        // `relative` makes the row its links' offsetParent, which centring measures from.
        className={cn("relative", PHONE_ROW, className)}
      >
        {children}
      </nav>
      <EdgeChevron side="start" shown={more.start} onClick={() => page(-1)} />
      <EdgeChevron side="end" shown={more.end} onClick={() => page(1)} />
    </div>
  );
}

/** A 44px tap area holding a small round chevron, on phones only. */
function EdgeChevron({
  side,
  shown,
  onClick,
}: {
  side: "start" | "end";
  shown: boolean;
  onClick: () => void;
}) {
  if (!shown) return null;
  const Icon = side === "start" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      aria-hidden="true"
      tabIndex={-1}
      data-scroll-chevron={side}
      onClick={onClick}
      className={cn(
        "absolute top-1/2 z-10 flex size-11 -translate-y-1/2 items-center sm:hidden",
        side === "start" ? "-left-2 justify-start pl-1" : "-right-2 justify-end pr-1",
      )}
    >
      <span className="flex size-7 items-center justify-center rounded-full border border-line-strong bg-surface text-ink-2">
        <Icon className="size-4" strokeWidth={2} />
      </span>
    </button>
  );
}

/** The phone row: one line, scrolling sideways with no scrollbar, snapping to items. */
const PHONE_ROW =
  "max-sm:flex max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:overscroll-x-contain max-sm:[scrollbar-width:none] max-sm:snap-x max-sm:snap-proximity max-sm:[&>*]:shrink-0 max-sm:[&>*]:snap-start motion-safe:scroll-smooth";
