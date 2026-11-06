"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A supplier photo in a fixed square box, loaded **straight from the supplier**.
 *
 * `contain`, never `cover`: photos arrive at wildly different aspect ratios
 * across eight shops, and cropping a component photo can remove the component.
 * The box is reserved before the image loads so a list of 24 rows does not shift
 * as it fills in.
 *
 * Why a plain `<img>` and not `next/image`: routing media through our own server
 * makes every thumbnail an outbound request from one IP, which is the same IP
 * the crawler is already blocked on at two suppliers — and it couples page speed
 * to how many *new* products get looked at. See
 * `docs/decisions/0003-supplier-images-load-direct.md`. The browser fetching
 * each photo itself spreads that load across visitors and costs us nothing.
 *
 * The three states are explicit because the page must stay usable while photos
 * are still arriving: the box is reserved and shows a spinner, the photo fades
 * in when it decodes, and a failure falls back to the glyph. `failed` covers
 * both "never had a photo" (about 2% of listings) and "the supplier rotated
 * their media", which is why it is wired to `onError` and not only to a missing
 * URL.
 */
export function ProductMedia({
  src,
  alt,
  className,
  priority = false,
}: {
  src: string | null;
  alt: string;
  className?: string;
  /** Above the fold: load it eagerly and at high priority instead of lazily. */
  priority?: boolean;
}) {
  // Tracked per-URL rather than as a bare boolean so that a row reused for a
  // different product (same DOM node, new src) starts from "loading" again
  // instead of showing the previous photo's state.
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const broken = !src || failed === src;
  const ready = !!src && loaded === src;

  return (
    <div
      // Says which state this box is in — loading, a photo, or the fallback that
      // covers both "no photo" and "the supplier's URL stopped resolving".
      data-media={broken ? "fallback" : ready ? "photo" : "loading"}
      className={cn(
        "relative aspect-square overflow-hidden rounded-md border border-rule bg-chip",
        className,
      )}
    >
      {broken ? (
        <PartGlyph />
      ) : (
        <>
          {!ready && <Spinner />}
          {/* Deliberate: photos are not optimised through our server.
              See docs/decisions/0003-supplier-images-load-direct.md. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            alt={alt}
            // Offscreen rows never fetch at all, so a 24-row page costs the
            // handful of photos actually on screen. This is what keeps the page
            // snappy while the photos arrive at their own pace.
            loading={priority ? "eager" : "lazy"}
            fetchPriority={priority ? "high" : "auto"}
            decoding="async"
            // Some shops serve a placeholder to off-site referrers. Sending no
            // referrer at all reads as a direct hit and sidesteps the naive
            // version of that check.
            referrerPolicy="no-referrer"
            onLoad={() => setLoaded(src)}
            onError={() => setFailed(src)}
            className={cn(
              "absolute inset-0 size-full object-contain p-1 transition-opacity duration-200",
              // Held hidden rather than unmounted: the browser has to be
              // decoding it for `onLoad` to ever fire.
              ready ? "opacity-100" : "opacity-0",
            )}
          />
        </>
      )}
    </div>
  );
}

/** Sized in `em` so one component works in a 48px row and a 400px gallery. */
function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="absolute inset-0 m-auto size-[1.25em] animate-spin rounded-full border-2 border-rule border-t-ink-muted motion-reduce:animate-none"
    />
  );
}

/** A DIP package outline — generic enough for any part, specific enough not to
 *  read as a broken image. */
function PartGlyph() {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      aria-hidden="true"
      className="absolute inset-0 m-auto size-1/2 text-ink-muted"
    >
      <rect x="9" y="8" width="14" height="16" rx="1.5" />
      <path d="M9 12H5M9 16H5M9 20H5M23 12h4M23 16h4M23 20h4" />
    </svg>
  );
}
