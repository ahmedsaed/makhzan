"use client";

import { ListTree, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * The phone's way into a department's tree (layout B with the owner's phone
 * changes, 18 November 2026): no category row on the page, but a floating
 * "{place} · Browse" pill at the bottom centre, clear of the home bar, that
 * opens the tree as a bottom sheet. Hidden from `md`, where the sidebar shows.
 *
 * The pill slides away while the page scrolls down and comes back on any
 * scroll up; with reduced motion it simply shows and hides (globals.css stops
 * every transition). Keyboard focus always brings it back.
 *
 * The sheet is a modal `<dialog>`: the browser makes the rest of the page
 * inert (the focus trap), gives it `aria-modal`, and closes it on Escape. It
 * is named by its heading, locks the page's scroll while open, closes on a
 * swipe down, a tap outside it or the choice of a link, and returns focus to
 * the pill.
 *
 * With JavaScript off the pill is a link to `#browse-tree`, the page's own
 * tree, which then shows on a phone too (`target:` in department-browse).
 */
export function BrowseSheet({
  place,
  title,
  children,
}: {
  /** Where the page is: "Resistors", "Components", "Electronics". */
  place: string;
  /** The sheet's heading: "Browse Electronics". */
  title: string;
  children: React.ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pill = useRef<HTMLAnchorElement>(null);
  const [shown, setShown] = useState(true);
  const [drag, setDrag] = useState(0);
  const start = useRef<number | null>(null);
  const headingId = useId();

  const close = useCallback(() => dialog.current?.close(), []);

  // Hide on scroll down, show on scroll up, one measurement a frame.
  useEffect(() => {
    let last = window.scrollY;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const y = window.scrollY;
        if (y > last + 6 && y > 80) setShown(false);
        else if (y < last - 6 || y <= 80) setShown(true);
        last = y;
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  useEffect(() => {
    const sheet = dialog.current;
    if (!sheet) return;
    const onClose = () => {
      document.documentElement.style.removeProperty("overflow");
      setDrag(0);
      pill.current?.focus();
    };
    sheet.addEventListener("close", onClose);
    return () => {
      sheet.removeEventListener("close", onClose);
      document.documentElement.style.removeProperty("overflow");
    };
  }, []);

  const open = (event: React.MouseEvent) => {
    const sheet = dialog.current;
    if (!sheet || typeof sheet.showModal !== "function") return; // follow the link
    event.preventDefault();
    document.documentElement.style.overflow = "hidden";
    sheet.showModal();
    // Start on the place the page is, not the first link.
    const here = sheet.querySelector<HTMLElement>("[aria-current='page']");
    here?.scrollIntoView({ block: "center" });
    (here ?? sheet.querySelector<HTMLElement>("button"))?.focus();
  };

  // Swipe down on the handle or the heading to close.
  const onPointerDown = (event: React.PointerEvent) => {
    start.current = event.clientY;
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (start.current !== null) setDrag(Math.max(0, event.clientY - start.current));
  };
  const onPointerUp = () => {
    if (start.current !== null && drag > 80) close();
    else setDrag(0);
    start.current = null;
  };

  return (
    <>
      <a
        ref={pill}
        href="#browse-tree"
        onClick={open}
        onFocus={() => setShown(true)}
        data-browse-pill
        data-shown={shown || undefined}
        aria-haspopup="dialog"
        className={cn(
          "fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] left-1/2 z-30 flex h-11 max-w-[calc(100vw-2rem)] -translate-x-1/2 items-center gap-2 rounded-full border border-line-strong bg-surface px-4 text-sm text-ink transition-[translate,opacity] duration-200 after:absolute after:-inset-1 after:content-[''] md:hidden",
          !shown && "pointer-events-none translate-y-[calc(100%+2rem)] opacity-0",
        )}
      >
        <ListTree aria-hidden="true" className="size-4 shrink-0 text-ink-2" />
        <span className="min-w-0 truncate font-semibold">{place}</span>
        <span className="shrink-0 text-ink-3">· Browse</span>
      </a>

      <dialog
        ref={dialog}
        aria-labelledby={headingId}
        data-browse-sheet
        onClick={(event) => {
          // A tap on the backdrop lands on the dialog itself, outside its panel.
          if (event.target === event.currentTarget) close();
          // Choosing a link closes the sheet as the page navigates.
          else if ((event.target as HTMLElement).closest("a")) close();
        }}
        style={drag ? { transform: `translateY(${drag}px)` } : undefined}
        className="m-0 mt-auto max-h-[85svh] w-full max-w-none overflow-hidden rounded-t-card border-t border-line bg-surface p-0 text-ink backdrop:bg-ink/40 md:hidden"
      >
        <div className="flex max-h-[85svh] flex-col">
          <div
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            data-sheet-handle
            className="touch-none border-b border-line px-4 pt-2"
          >
            <span
              aria-hidden="true"
              className="mx-auto block h-1 w-10 rounded-full bg-line-strong"
            />
            <div className="flex items-center justify-between">
              <h2 id={headingId} className="font-display text-base font-bold">
                {title}
              </h2>
              <button
                type="button"
                onClick={close}
                aria-label="Close"
                className="-me-2 grid size-11 place-items-center text-ink-2 hover:text-ink"
              >
                <X aria-hidden="true" className="size-5" />
              </button>
            </div>
          </div>
          <div className="overflow-y-auto overscroll-contain px-2 py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))]">
            {children}
          </div>
        </div>
      </dialog>
    </>
  );
}
