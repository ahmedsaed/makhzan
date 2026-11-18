"use client";

import { Children, useEffect, useLayoutEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A labelled list of links that, on a phone, is one line scrolling sideways
 * inside itself (the owner's decision of 2026-11-18: wrapped group tiles and
 * category chips pushed the products a long way down). From `sm` it is
 * whatever layout `className` gives the list; the phone row is PHONE_ROW, all
 * `max-sm:`, so tablet and desktop are untouched. (It stays in this module: a
 * constant exported from a client module reaches a server component as a
 * reference, not a string.)
 *
 * A `nav` named by `label` holding a `ul`, one `li` per child, so a screen
 * reader announces the row and how many links it holds. The list is the
 * scroller: a plain `overflow-x-auto`, which scrolls with momentum and works
 * with JavaScript off. On top of it:
 * - the selected link (`aria-current`) is centred before first paint, without
 *   moving the page;
 * - a link that takes keyboard focus is brought clear of the edge fades, and
 *   the list's padding keeps its focus ring inside the scroller, which clips;
 * - snapping leaves `scroll-padding` the width of the fade, so an item never
 *   comes to rest under it;
 * - two cues that there is more: the next item shows partly, and the edge
 *   with hidden content fades (globals.css, `data-more-start` /
 *   `data-more-end`), only that edge, sharp again once the row reaches it.
 *   No chevron buttons (the owner, 2026-11-18);
 * - no animation under `prefers-reduced-motion`: every scroll is instant.
 */
export function ScrollRow({
  label,
  className,
  style,
  children,
}: {
  label: string;
  /** The list's layout from `sm` up, plus any phone padding it needs. */
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLUListElement>(null);
  const [more, setMore] = useState({ start: false, end: false });

  // Before paint, so a selected item far along the row does not visibly jump.
  useLayoutEffect(() => {
    const row = ref.current;
    const current = row?.querySelector<HTMLElement>("[aria-current]");
    if (!row || !current || row.scrollWidth <= row.clientWidth + 1) return;
    row.scrollLeft = current.offsetLeft - (row.clientWidth - current.offsetWidth) / 2;
  }, []);

  useEffect(() => {
    const row = ref.current;
    if (!row) return;
    const measure = () => {
      const scrolls = row.scrollWidth > row.clientWidth + 1;
      const start = scrolls && row.scrollLeft > 1;
      const end = scrolls && row.scrollLeft + row.clientWidth < row.scrollWidth - 1;
      setMore((was) => (was.start === start && was.end === end ? was : { start, end }));
    };
    let frame = 0;
    const onScroll = () => {
      if (!frame) {
        frame = requestAnimationFrame(() => {
          frame = 0;
          measure();
        });
      }
    };
    const onFocus = (event: FocusEvent) => {
      const item = (event.target as HTMLElement).closest<HTMLElement>("a");
      if (!item || !row.contains(item)) return;
      const box = item.getBoundingClientRect();
      const frameBox = row.getBoundingClientRect();
      // Clear of the 2.5rem fade on either side, or centred.
      if (box.left >= frameBox.left + 40 && box.right <= frameBox.right - 40) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      row.scrollTo({
        left: item.offsetLeft - (row.clientWidth - item.offsetWidth) / 2,
        behavior: reduce ? "auto" : "smooth",
      });
    };

    measure();
    // The row's own size, not only the window's: fonts loading or a parent
    // changing width can make it start or stop overflowing.
    const resize = new ResizeObserver(measure);
    resize.observe(row);
    row.addEventListener("scroll", onScroll, { passive: true });
    row.addEventListener("focusin", onFocus);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      row.removeEventListener("scroll", onScroll);
      row.removeEventListener("focusin", onFocus);
    };
  }, []);

  return (
    <nav aria-label={label}>
      <ul
        ref={ref}
        // An explicit role: Safari drops list semantics from `list-style: none`.
        role="list"
        data-scroll-row
        data-more-start={more.start || undefined}
        data-more-end={more.end || undefined}
        style={style}
        // `relative` makes the list its links' offsetParent, which centring measures from.
        className={cn("relative", PHONE_ROW, className)}
      >
        {Children.map(children, (child) => (child ? <li>{child}</li> : null))}
      </ul>
    </nav>
  );
}

/**
 * The phone row: one line, scrolling sideways with no scrollbar, snapping to
 * items clear of the 2.5rem fade, padded 6px inline so the first and last
 * focus rings (2px outline, 2px offset) are not clipped.
 */
const PHONE_ROW =
  "max-sm:flex max-sm:flex-nowrap max-sm:overflow-x-auto max-sm:overscroll-x-contain max-sm:[scrollbar-width:none] max-sm:snap-x max-sm:snap-proximity max-sm:scroll-px-10 max-sm:-mx-1.5 max-sm:px-1.5 max-sm:[&>li]:shrink-0 max-sm:[&>li]:snap-start motion-safe:scroll-smooth";
