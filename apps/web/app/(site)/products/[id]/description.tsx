"use client";

import { useCallback, useEffect, useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A shop's own description, capped at about three quarters of the screen's
 * height (about 28 lines on a laptop) and faded out at the cut, with "Read
 * more". Capped by height rather than by lines, so it fills most of a phone,
 * a laptop or a tall monitor alike without forcing a long scroll.
 *
 * "Read more" shows only when the text really overflows the cap, measured in
 * the browser (`scrollHeight` against `clientHeight`) and measured again when
 * the box changes size: on resize, and when a shop's tab is switched to and
 * its panel appears. A short description shows in full with no button.
 *
 * The cap is applied by JavaScript, once it runs: the server renders the text
 * in full, so without JavaScript nothing is ever hidden behind a button that
 * cannot work.
 *
 * Supplier prose, shown as written and never translated; `dir="auto"` for the
 * few that are in Arabic.
 */
export function Description({ text }: { text: string }) {
  const id = useId();
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [overflows, setOverflows] = useState(false);
  const [open, setOpen] = useState(false);
  const ref = useCallback((node: HTMLDivElement | null) => setBox(node), []);
  // Only once mounted (`box`) and while closed.
  const capped = box !== null && !open;

  useEffect(() => {
    if (!box || open) return;
    // Reports once on observing, then on every change of the box's size.
    const observer = new ResizeObserver(() =>
      setOverflows(box.scrollHeight > box.clientHeight + 1),
    );
    observer.observe(box);
    return () => observer.disconnect();
  }, [box, open]);

  const collapse = () => {
    setOpen(false);
    // Back to where the text starts, if the reader had scrolled past it.
    if (box && box.getBoundingClientRect().top < 0) box.scrollIntoView({ block: "start" });
  };

  return (
    <section data-description className="mt-6 lg:mt-5">
      <h3 className="text-[15px]">Description</h3>
      <div
        ref={ref}
        id={id}
        data-capped={capped && overflows ? "" : undefined}
        className={cn("relative mt-1.5", capped && "max-h-[max(16rem,75dvh)] overflow-hidden")}
      >
        <p dir="auto" className="text-sm leading-relaxed whitespace-pre-line text-ink-2">
          {text}
        </p>
        {capped && overflows && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-linear-to-t from-ground"
          />
        )}
      </div>
      {overflows && (
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={open ? collapse : () => setOpen(true)}
          className="inline-flex h-11 cursor-pointer items-center text-sm font-medium text-link underline"
        >
          {open ? "Show less" : "Read more"}
        </button>
      )}
    </section>
  );
}
