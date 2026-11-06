"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A supplier photo in a fixed square white frame, loaded **straight from the
 * supplier** (rule S5).
 *
 * White in both themes: supplier photos are shot on white, and a dark frame
 * around one reads as a hole in the page. `contain`, never `cover`: photos
 * arrive at wildly different aspect ratios, and cropping a component photo can
 * remove the component. The box is reserved before the image loads so a list of
 * 24 rows does not shift as it fills in.
 *
 * Why a plain `<img>` and not `next/image`: routing media through our own server
 * makes every thumbnail an outbound request from one IP, which is the same IP
 * the crawler is already blocked on at two suppliers — and it couples page speed
 * to how many *new* products get looked at. See
 * `docs/decisions/0003-supplier-images-load-direct.md`.
 *
 * The three states are explicit because the page must stay usable while photos
 * are still arriving: the box is reserved and shows a spinner, the photo fades
 * in when it decodes, and a failure falls back to the glyph. `failed` covers
 * both "never had a photo" and "the supplier rotated their media", which is why
 * it is wired to `onError` and not only to a missing URL.
 */
export function PhotoFrame({
  src,
  alt,
  size,
  className,
  priority = false,
}: {
  src: string | null;
  /** Describes the product, not the photo: usually its title. */
  alt: string;
  /** Edge length in px. Omit to fill the parent's width (cards, galleries). */
  size?: number;
  className?: string;
  /** Above the fold: load it eagerly and at high priority instead of lazily. */
  priority?: boolean;
}) {
  // Tracked per-URL rather than as a bare boolean so that a frame reused for a
  // different product (same DOM node, new src) starts from "loading" again
  // instead of showing the previous photo's state.
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const broken = !src || failed === src;
  const ready = !!src && loaded === src;

  return (
    <div
      // Says which state this frame is in — loading, a photo, or the fallback
      // that covers both "no photo" and "the supplier's URL stopped resolving".
      data-media={broken ? "fallback" : ready ? "photo" : "loading"}
      style={size ? { width: size, height: size } : undefined}
      className={cn(
        "relative aspect-square shrink-0 overflow-hidden rounded-card border border-line bg-photo-frame",
        !size && "w-full",
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
            // handful of photos actually on screen.
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
              "absolute inset-0 size-full object-contain p-1.5 transition-opacity duration-200",
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

/** Sized in `em` so one component works in a 72px row and a 400px gallery.
 *  `ink-3` reads on the white frame in both themes. */
function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="absolute inset-0 m-auto size-[1.25em] animate-spin rounded-full border-2 border-line-strong border-t-ink-3 motion-reduce:animate-none"
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
      className="absolute inset-0 m-auto size-1/2 text-ink-3"
    >
      <rect x="9" y="8" width="14" height="16" rx="1.5" />
      <path d="M9 12H5M9 16H5M9 20H5M23 12h4M23 16h4M23 20h4" />
    </svg>
  );
}
