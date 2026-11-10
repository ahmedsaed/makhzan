"use client";

import { useCallback, useState } from "react";

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
 *
 * `shop` names the shop the photo comes from. It is drawn as a small badge in
 * the bottom-left corner, over the photo and never in it: an element laid on
 * top of the `<img>`, which stays the shop's own file, untouched (decision
 * 0003: we show the shop's photo, we do not copy or alter it). The badge is
 * `aria-hidden`; the shop is in the alt text instead, so a screen reader hears
 * it once. A fixed frame under `BADGE_MIN_SIZE` (the 72px list-row
 * thumbnail) gets no badge: at that size a readable one runs most of the
 * frame's width and covers the bottom fifth of the part, so the shop is left
 * to the alt text and a hover title there (and a one-shop row names its shop
 * beside the photo anyway). A frame from that size up to `COMPACT_BELOW` (the
 * 104px thumbnail beside a product's title on a phone) gets a smaller badge,
 * which fits the corner the photo's own white margin leaves. No badge on the
 * fallback glyph: there is no photo to credit.
 */
/** Fixed-size frames smaller than this carry no badge (see PhotoFrame). */
export const BADGE_MIN_SIZE = 96;
/** Fixed-size frames smaller than this carry the compact badge. */
const COMPACT_BELOW = 120;

/** "SG90 Servo — photo from Shop A": the alt text of a photo credited to a shop. */
export function photoAlt(alt: string, shop: string | null | undefined): string {
  const name = shop?.trim();
  return name && alt ? `${alt} — photo from ${name}` : alt;
}

export function PhotoFrame({
  src,
  alt,
  shop = null,
  size,
  className,
  priority = false,
  preloaded = false,
}: {
  src: string | null;
  /** Describes the product, not the photo: usually its title. Empty for a
   *  decorative photo, which then stays silent about its shop too. */
  alt: string;
  /** The shop the photo comes from, for the badge on it. Unknown (an older
   *  API response, a product not yet rebuilt): no badge. */
  shop?: string | null;
  /** Edge length in px. Omit to fill the parent's width (cards, galleries). */
  size?: number;
  className?: string;
  /** Above the fold: load it eagerly and at high priority instead of lazily. */
  priority?: boolean;
  /** The caller has already loaded this exact URL: show it at once, without
   *  the loading state (a thumbnail swapped for its original). */
  preloaded?: boolean;
}) {
  // Tracked per-URL rather than as a bare boolean so that a frame reused for a
  // different product (same DOM node, new src) starts from "loading" again
  // instead of showing the previous photo's state.
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  // A photo can finish loading before React hydrates and attaches `onLoad`
  // (server-rendered, or from the cache), and then the event never reaches
  // us: the frame would spin forever over a photo that is there. So the
  // element's own state is read once it is mounted.
  const settle = useCallback(
    (img: HTMLImageElement | null) => {
      if (!img || !src || !img.complete) return;
      if (img.naturalWidth > 0) setLoaded(src);
      else setFailed(src);
    },
    [src],
  );

  const broken = !src || failed === src;
  const ready = !!src && (preloaded || loaded === src);
  const credited = shop?.trim() || null;
  const badged = !!credited && !broken && (!size || size >= BADGE_MIN_SIZE);

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
            ref={settle}
            src={src}
            alt={photoAlt(alt, credited)}
            // Where the badge is left off, a pointer still finds out whose it is.
            title={credited && alt && !badged ? `Photo from ${credited}` : undefined}
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
          {badged && <ShopBadge shop={credited} compact={!!size && size < COMPACT_BELOW} />}
        </>
      )}
    </div>
  );
}

/**
 * The shop's name on the photo: dark at 80% with white text in both themes,
 * since it is read against the photo (white more often than not) rather than
 * the page. Small, one line, truncated. In a gallery it sits level with
 * "2 / 3" in the far corner and stops short of it (`data-photo-count` on an
 * ancestor). Not a link: the whole frame usually is one.
 */
function ShopBadge({ shop, compact }: { shop: string; compact: boolean }) {
  return (
    <span
      aria-hidden="true"
      data-photo-shop={compact ? "compact" : ""}
      className={cn(
        "pointer-events-none absolute truncate rounded-full bg-photo-tag/80 font-medium text-photo-tag-ink",
        compact
          ? "start-1 bottom-1 max-w-[calc(100%-0.5rem)] px-1.5 text-[10px] leading-3.5"
          : "start-1.5 bottom-1.5 max-w-[calc(100%-0.75rem)] px-2 py-px text-[11px] leading-4",
        "[[data-photo-count]_&]:start-2.5 [[data-photo-count]_&]:bottom-2.5 [[data-photo-count]_&]:max-w-[calc(100%-6rem)]",
      )}
    >
      {shop}
    </span>
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
