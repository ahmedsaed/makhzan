"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/** Where a horizontal scroll strip stands. */
export type StripState = {
  /** Wider than its box: there is somewhere to scroll. */
  scrollable: boolean;
  atStart: boolean;
  atEnd: boolean;
  /** The item nearest the strip's start edge, from 0. */
  index: number;
};

const AT_REST: StripState = { scrollable: false, atStart: true, atEnd: true, index: 0 };

/** The distance from one item's start to the next one's: its width plus the gap. */
function stepOf(track: HTMLElement): number {
  const [first, second] = Array.from(track.children) as HTMLElement[];
  if (!first) return track.clientWidth;
  if (!second) return first.getBoundingClientRect().width;
  return second.getBoundingClientRect().left - first.getBoundingClientRect().left;
}

function stateOf(track: HTMLElement): StripState {
  const max = track.scrollWidth - track.clientWidth;
  const step = stepOf(track);
  return {
    scrollable: max > 1,
    atStart: track.scrollLeft <= 1,
    atEnd: track.scrollLeft >= max - 1,
    index: step > 0 ? Math.round(track.scrollLeft / step) : 0,
  };
}

/** One item back (-1) or on (+1). Snapping decides exactly where it lands. */
export function stepStrip(track: HTMLElement | null, direction: -1 | 1) {
  track?.scrollBy({ left: direction * stepOf(track), behavior: "smooth" });
}

/** Straight to item `index`, without animating: for opening on a photo. */
export function jumpStrip(track: HTMLElement, index: number) {
  track.scrollTo({ left: index * stepOf(track), behavior: "instant" });
}

/**
 * Follows a scroll-snap strip: whether it can scroll, whether it is at either
 * end, and which item leads. The strip keeps scrolling and snapping on its own
 * (swipe, trackpad, keyboard); this only reads where it is.
 */
export function useStrip(track: HTMLElement | null): StripState {
  const [state, setState] = useState<StripState>(AT_REST);
  useEffect(() => {
    if (!track) return;
    const measure = () => setState(stateOf(track));
    track.addEventListener("scroll", measure, { passive: true });
    // Also reports once on observing, which takes the first measurement.
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    return () => {
      track.removeEventListener("scroll", measure);
      observer.disconnect();
    };
  }, [track]);
  return state;
}

/**
 * A tap area a little beyond a round button's edge: a circle 44px across is
 * narrower than 44px near its sides, and a finger does not aim at the centre.
 */
export const TAP_EXTENSION = "after:absolute after:-inset-1.5 after:content-['']";

/** A round 44px arrow button (S4), in the surface colours over a photo or row. */
export function ArrowButton({
  direction,
  label,
  disabled,
  onClick,
  className,
}: {
  direction: -1 | 1;
  label: string;
  disabled: boolean;
  onClick: () => void;
  className?: string;
}) {
  const Icon = direction < 0 ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "absolute top-1/2 z-10 inline-flex size-11 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full border border-line-strong bg-surface text-ink",
        "outline-offset-2 outline-link hover:border-ink-3 focus-visible:outline-2",
        "disabled:cursor-default disabled:opacity-40 disabled:hover:border-line-strong",
        TAP_EXTENSION,
        direction < 0 ? "start-2" : "end-2",
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-5" />
    </button>
  );
}

/**
 * Previous and next buttons over a horizontal scroll strip: its child marked
 * `data-carousel-track`. The strip is server-rendered and swipes and snaps
 * without JavaScript; the buttons need it, so they appear only once it runs,
 * and only while the strip is wider than its box. Each moves one item and is
 * disabled at its end.
 */
export function Carousel({
  children,
  previous,
  next,
  buttonClassName,
}: {
  children: ReactNode;
  /** The buttons' accessible names, e.g. "Previous photo". */
  previous: string;
  next: string;
  /** e.g. hide them where the strip turns into a grid. */
  buttonClassName?: string;
}) {
  const [track, setTrack] = useState<HTMLElement | null>(null);
  const strip = useStrip(track);
  // Stable, so React hands it the node once rather than on every render.
  const box = useCallback((node: HTMLDivElement | null) => {
    setTrack(node?.querySelector<HTMLElement>("[data-carousel-track]") ?? null);
  }, []);
  return (
    <div ref={box} className="relative">
      {children}
      {strip.scrollable && (
        <>
          <ArrowButton
            direction={-1}
            label={previous}
            disabled={strip.atStart}
            onClick={() => stepStrip(track, -1)}
            className={buttonClassName}
          />
          <ArrowButton
            direction={1}
            label={next}
            disabled={strip.atEnd}
            onClick={() => stepStrip(track, 1)}
            className={buttonClassName}
          />
        </>
      )}
    </div>
  );
}
