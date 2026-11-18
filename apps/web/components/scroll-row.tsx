"use client";

import { useEffect, useRef, useState } from "react";

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
 * - a link that takes keyboard focus is brought clear of the edge fades;
 * - two cues that there is more: the next item shows partly, and the edge
 *   with hidden content fades (globals.css, `data-more-start` /
 *   `data-more-end`), only that edge, sharp again once the row reaches it.
 *   No chevron buttons (the owner, 2026-11-18): the row is a plain list of
 *   links, reachable by keyboard and screen reader;
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

  useEffect(() => {
    const row = ref.current;
    if (!row) return;
    const centre = (item: HTMLElement, smooth: boolean) => {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      row.scrollTo({
        left: item.offsetLeft - (row.clientWidth - item.offsetWidth) / 2,
        behavior: smooth && !reduce ? "smooth" : "auto",
      });
    };
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
      // Clear of the 2.5rem fade on either side, or centred.
      if (box.left < frame.left + 40 || box.right > frame.right - 40) centre(item, true);
    };
    row.addEventListener("scroll", measure, { passive: true });
    row.addEventListener("focusin", onFocus);
    window.addEventListener("resize", measure);
    return () => {
      row.removeEventListener("scroll", measure);
      row.removeEventListener("focusin", onFocus);
      window.removeEventListener("resize", measure);
    };
  }, []);

  return (
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
  );
}

/** The phone row: one line, scrolling sideways with no scrollbar, snapping to items. */
const PHONE_ROW =
  "max-sm:flex max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:overscroll-x-contain max-sm:[scrollbar-width:none] max-sm:snap-x max-sm:snap-proximity max-sm:[&>*]:shrink-0 max-sm:[&>*]:snap-start motion-safe:scroll-smooth";
