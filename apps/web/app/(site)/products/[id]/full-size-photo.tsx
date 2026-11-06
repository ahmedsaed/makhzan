"use client";

import { type ComponentProps, useEffect, useRef, useState } from "react";

import { PhotoFrame } from "@/components/photo-frame";
import { fullSizeCandidates } from "@/lib/full-size";

/**
 * A product-page photo, upgraded to the full-size original when its URL is a
 * shop's cached thumbnail (lib/full-size.ts).
 *
 * The thumbnail is what the server renders, so the photo is there without
 * JavaScript. In the browser each candidate original is tried in turn, off
 * screen, and swapped in only once it has loaded: a guess that 404s never
 * shows as a broken photo, and when every guess fails the thumbnail stays.
 *
 * Only once the photo is at least half on screen: an original costs the shop
 * real bandwidth, and a gallery of eight would otherwise download eight of
 * them for a visitor who looks at the first. A gallery hidden by CSS (the
 * phone layout of a several-shop product) never intersects, so costs nothing.
 */
export function FullSizePhoto({ src, ...props }: ComponentProps<typeof PhotoFrame>) {
  const [upgraded, setUpgraded] = useState<{ from: string; to: string } | null>(null);
  const [seen, setSeen] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const hasCandidates = !!src && fullSizeCandidates(src).length > 0;

  useEffect(() => {
    const node = box.current;
    if (!node || !src || !hasCandidates || seen === src) return;
    if (typeof IntersectionObserver === "undefined") return;
    // The default root clips by every scrolling ancestor, so a photo further
    // along the gallery strip is not "visible" until it is swiped to.
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(src);
          observer.disconnect();
        }
      },
      { threshold: 0.5 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [src, hasCandidates, seen]);

  useEffect(() => {
    const candidates = src ? fullSizeCandidates(src) : [];
    if (!src || candidates.length === 0 || seen !== src) return;
    let cancelled = false;
    let probe: HTMLImageElement | null = null;

    const attempt = (index: number) => {
      if (cancelled || index >= candidates.length) return;
      probe = new window.Image();
      // The same as the frame's own <img>: no referrer to the shop.
      probe.referrerPolicy = "no-referrer";
      probe.onload = () => {
        if (!cancelled) setUpgraded({ from: src, to: candidates[index] });
      };
      probe.onerror = () => attempt(index + 1);
      probe.src = candidates[index];
    };
    attempt(0);

    return () => {
      cancelled = true;
      if (probe) probe.onload = probe.onerror = null;
    };
  }, [src, seen]);

  const isUpgraded = !!upgraded && upgraded.from === src;
  return (
    <div ref={box}>
      {/* Already decoded by the probe: no spinner flash on the swap. */}
      <PhotoFrame src={isUpgraded ? upgraded.to : src} preloaded={isUpgraded} {...props} />
    </div>
  );
}
