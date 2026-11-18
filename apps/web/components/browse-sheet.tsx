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
 * inert (the focus trap) and gives it `aria-modal`. It is named by its
 * heading, locks the page's scroll while open, and closes on a swipe down, a
 * tap outside it, Escape, Close or the choice of a link, then puts focus back
 * on the pill itself: the dialog's own restore returns focus to whatever had
 * it before, and in Safari and Firefox on macOS a click does not focus a
 * link, so that would be the page's body. Widening the window past `md` (a
 * phone turned on its side, a resized window) closes it at once: the sheet is
 * hidden there and the sidebar shows, and a hidden modal would leave the page
 * inert and unscrollable.
 *
 * Motion (the owner's sheet-motion mockup, option A; the keyframes are in
 * globals.css): it rises over 250ms as the backdrop fades in, and sinks over
 * 200ms before close() is called. A swipe on the handle moves it with the
 * finger and thins the backdrop; let go past the threshold (80px or a quarter
 * of the sheet, at most half) or with a flick (over 0.5px/ms) and it glides
 * out at the finger's speed, in 120 to 240ms, else it springs back in 380ms
 * with a slight overshoot. Under reduced motion all of that is instant, and
 * closing never waits for an animation that will not run.
 *
 * With JavaScript off the pill is a link to `#browse-tree`, the page's own
 * tree, which then shows on a phone too (`target:` in department-browse).
 */

const CLOSE_MS = 200;
const SPRING_MS = 380;
const SPRING = "cubic-bezier(0.3, 1.35, 0.5, 1)";
const GLIDE = "cubic-bezier(0.25, 0.6, 0.4, 1)";

type Drag = {
  y0: number;
  y: number;
  t: number;
  /** Downward speed, px/ms, smoothed. */
  vy: number;
  dy: number;
  height: number;
  captured: boolean;
};

function reducedMotion() {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

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
  const drag = useRef<Drag | null>(null);
  const timer = useRef(0);
  const headingId = useId();

  /** Back to rest: no inline motion left on the sheet or its backdrop. */
  const settle = useCallback(() => {
    const sheet = dialog.current;
    if (!sheet) return;
    sheet.style.removeProperty("transform");
    sheet.style.removeProperty("transition");
    sheet.style.removeProperty("--sheet-backdrop");
    sheet.style.removeProperty("--sheet-backdrop-ms");
  }, []);

  /** Close now: the dialog shuts and the close handler tidies up. */
  const finish = useCallback(() => {
    const sheet = dialog.current;
    window.clearTimeout(timer.current);
    if (!sheet) return;
    sheet.removeAttribute("data-closing");
    // Released here as well as on the close event, which comes a task later:
    // a close under reduced motion is then over by the time it returns.
    document.documentElement.style.removeProperty("overflow");
    if (sheet.open) sheet.close();
  }, []);

  /** Close with the 200ms slide down, or at once under reduced motion. */
  const close = useCallback(() => {
    const sheet = dialog.current;
    if (!sheet?.open || sheet.hasAttribute("data-closing")) return;
    if (reducedMotion()) return finish();
    settle();
    sheet.setAttribute("data-closing", "");
    const onEnd = (event: AnimationEvent) => {
      if (event.target !== sheet) return;
      sheet.removeEventListener("animationend", onEnd);
      finish();
    };
    sheet.addEventListener("animationend", onEnd);
    // The animation may never run (the sheet hidden, a browser without it).
    timer.current = window.setTimeout(() => {
      sheet.removeEventListener("animationend", onEnd);
      finish();
    }, CLOSE_MS + 100);
  }, [finish, settle]);

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
      window.clearTimeout(timer.current);
      document.documentElement.style.removeProperty("overflow");
      sheet.removeAttribute("data-closing");
      settle();
      drag.current = null;
      pill.current?.focus();
    };
    // Escape: the slide down, not the browser's instant close.
    const onCancel = (event: Event) => {
      event.preventDefault();
      close();
    };
    // From `md` the sheet is hidden and the sidebar shows: close it at once, or
    // the page behind would stay inert under a modal nobody can see.
    const wide =
      typeof window.matchMedia === "function" ? window.matchMedia("(min-width: 48rem)") : null;
    const onWide = () => {
      if (wide?.matches && sheet.open) finish();
    };
    sheet.addEventListener("close", onClose);
    sheet.addEventListener("cancel", onCancel);
    wide?.addEventListener("change", onWide);
    return () => {
      window.clearTimeout(timer.current);
      sheet.removeEventListener("close", onClose);
      sheet.removeEventListener("cancel", onCancel);
      wide?.removeEventListener("change", onWide);
      document.documentElement.style.removeProperty("overflow");
    };
  }, [close, finish, settle]);

  const open = (event: React.MouseEvent) => {
    const sheet = dialog.current;
    if (!sheet || typeof sheet.showModal !== "function") return; // follow the link
    event.preventDefault();
    document.documentElement.style.overflow = "hidden";
    settle();
    sheet.showModal(); // the rise and the backdrop's fade are CSS, on [open]
    // Start on the place the page is, not the first link.
    const here = sheet.querySelector<HTMLElement>("[aria-current='page']");
    here?.scrollIntoView({ block: "center" });
    (here ?? sheet.querySelector<HTMLElement>("button"))?.focus();
  };

  // Swipe down on the handle or the heading to close.
  const onPointerDown = (event: React.PointerEvent) => {
    const sheet = dialog.current;
    // A press on the Close button is a click, never the start of a swipe.
    if (!sheet?.open || (event.target as HTMLElement).closest("button")) return;
    drag.current = {
      y0: event.clientY,
      y: event.clientY,
      t: event.timeStamp,
      vy: 0,
      dy: 0,
      height: sheet.offsetHeight,
      captured: false,
    };
  };
  const onPointerMove = (event: React.PointerEvent) => {
    const d = drag.current;
    const sheet = dialog.current;
    if (!d || !sheet) return;
    const raw = event.clientY - d.y0;
    // Captured once it is plainly a drag, so a release outside the handle (a
    // mouse dragged off it) still ends the gesture here; not on the press,
    // which would swallow a click.
    if (!d.captured && Math.abs(raw) > 4) {
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // A pointer that is no longer active (or a synthetic one) cannot be captured.
      }
      d.captured = true;
      sheet.style.transition = "none";
      sheet.style.setProperty("--sheet-backdrop-ms", "0ms");
    }
    if (!d.captured) return;
    const dt = event.timeStamp - d.t;
    if (dt > 0) d.vy = 0.8 * ((event.clientY - d.y) / dt) + 0.2 * d.vy;
    d.y = event.clientY;
    d.t = event.timeStamp;
    // Down follows the finger; up resists, and stops at 16px.
    d.dy = raw >= 0 ? raw : -16 * (1 - Math.exp(raw / 40));
    sheet.style.transform = `translateY(${d.dy}px)`;
    sheet.style.setProperty(
      "--sheet-backdrop",
      String(Math.max(0, 1 - Math.max(0, d.dy) / d.height)),
    );
  };
  const onPointerUp = (event: React.PointerEvent) => {
    const d = drag.current;
    const sheet = dialog.current;
    drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (!d?.captured || !sheet) return;
    if (event.timeStamp - d.t > 80) d.vy = 0; // held still before letting go
    const past = d.dy > Math.min(Math.max(80, d.height * 0.25), d.height * 0.5);
    const reduce = reducedMotion();
    if (past || d.vy > 0.5) {
      // Glide out at the finger's speed, then close.
      const rest = d.height - d.dy;
      const ms = reduce ? 0 : Math.round(Math.min(240, Math.max(120, rest / Math.max(d.vy, 1.2))));
      sheet.style.transition = `transform ${ms}ms ${GLIDE}`;
      sheet.style.setProperty("--sheet-backdrop-ms", `${ms}ms`);
      sheet.style.transform = `translateY(${d.height}px)`;
      sheet.style.setProperty("--sheet-backdrop", "0");
      if (ms === 0) finish();
      else timer.current = window.setTimeout(finish, ms);
    } else {
      // Spring back, with a slight overshoot.
      sheet.style.transition = reduce ? "none" : `transform ${SPRING_MS}ms ${SPRING}`;
      sheet.style.setProperty("--sheet-backdrop-ms", reduce ? "0ms" : "200ms");
      sheet.style.transform = "translateY(0px)";
      sheet.style.removeProperty("--sheet-backdrop");
      if (reduce) settle();
      else
        timer.current = window.setTimeout(() => {
          if (!drag.current) settle();
        }, SPRING_MS + 40);
    }
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
        // Not clipped: the ::after under it fills the gap when the spring
        // overshoots upward; the tree scrolls inside its own box.
        className="m-0 mt-auto max-h-[85svh] w-full max-w-none overflow-visible rounded-t-card border-t border-line bg-surface p-0 text-ink backdrop:bg-ink/40 after:absolute after:inset-x-0 after:top-full after:h-12 after:bg-surface after:content-[''] md:hidden"
      >
        <div className="flex max-h-[85svh] flex-col">
          <div
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            data-sheet-handle
            className="cursor-grab touch-none border-b border-line px-4 pt-2 select-none active:cursor-grabbing"
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
          <div className="overflow-y-auto overscroll-contain p-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))]">
            {children}
          </div>
        </div>
      </dialog>
    </>
  );
}
