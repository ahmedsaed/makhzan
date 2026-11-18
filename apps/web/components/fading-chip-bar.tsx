"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * The chip bar (components/chips.tsx `ChipBar`) with an edge fade on a phone:
 * an edge that hides chips fades out (globals.css, `data-scroll-fade`), and is
 * sharp again once the bar reaches it, so a chip cut off at the edge reads as
 * "there is more" rather than as a broken one. No arrow. The browse pages'
 * toolbar uses it, where Price would otherwise sit cut off at 390px.
 */
export function FadingChipBar({
  label = "Quick filters",
  children,
  className,
}: {
  label?: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLElement>(null);
  const [more, setMore] = useState({ start: false, end: false });

  useEffect(() => {
    const bar = ref.current;
    if (!bar) return;
    const measure = () => {
      const scrolls = bar.scrollWidth > bar.clientWidth + 1;
      const start = scrolls && bar.scrollLeft > 1;
      const end = scrolls && bar.scrollLeft + bar.clientWidth < bar.scrollWidth - 1;
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
    measure();
    // The bar's own size, and each chip's: a chip that grows or shrinks (a
    // price set, a font loading) changes what overflows without the bar
    // resizing. Chips added or removed are observed as they come.
    const resize = new ResizeObserver(measure);
    const observeAll = () => {
      resize.disconnect();
      resize.observe(bar);
      for (const chip of bar.children) resize.observe(chip);
      measure();
    };
    observeAll();
    const mutations = new MutationObserver(observeAll);
    mutations.observe(bar, { childList: true });
    bar.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      mutations.disconnect();
      bar.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <nav
      ref={ref}
      aria-label={label}
      data-scroll-fade
      data-more-start={more.start || undefined}
      data-more-end={more.end || undefined}
      className={cn(
        "-my-1 flex [scrollbar-width:none] items-center gap-2 overflow-x-auto py-1",
        className,
      )}
    >
      {children}
    </nav>
  );
}
