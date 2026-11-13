"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

/** One stretch of the chart, in fractions of the plot (0–1). */
export type HoverSegment = {
  from: number;
  to: number;
  /** Where the line is, from the top; 0.5 for a gap. */
  top: number;
  date: string;
  text: string;
  shop: string | null;
};

/**
 * The chart's only JavaScript: a crosshair and a tooltip naming the price,
 * the day it took effect and whose it was. Without JavaScript the plot is
 * the same and the table under it says the same things.
 */
export function ChartHover({
  segments,
  className,
  children,
}: {
  segments: HoverSegment[];
  className?: string;
  children: React.ReactNode;
}) {
  const [at, setAt] = useState<number | null>(null);
  const segment =
    at === null
      ? null
      : (segments.find((s) => at >= s.from && at < s.to) ?? segments[segments.length - 1]);
  return (
    <div
      className={className}
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        setAt(Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)));
      }}
      onPointerLeave={() => setAt(null)}
    >
      {children}
      {segment && at !== null && (
        <>
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 w-px bg-ink-3"
            style={{ left: `${at * 100}%` }}
          />
          <span
            aria-hidden="true"
            data-chart-tip
            className={cn(
              "pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-control border border-line-strong bg-surface px-2 py-1.5 text-xs whitespace-nowrap text-ink",
            )}
            style={{
              left: `${Math.min(Math.max(at, 0.15), 0.85) * 100}%`,
              top: `calc(${segment.top * 100}% - 8px)`,
            }}
          >
            <span className="block text-ink-2">from {segment.date}</span>
            <span className="figure">{segment.text}</span>
            {segment.shop && <span className="block text-ink-2">{segment.shop}</span>}
          </span>
        </>
      )}
    </div>
  );
}
