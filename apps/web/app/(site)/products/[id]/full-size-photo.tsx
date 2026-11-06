"use client";

import { type ComponentProps, useEffect, useState } from "react";

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
 */
export function FullSizePhoto({ src, ...props }: ComponentProps<typeof PhotoFrame>) {
  const [upgraded, setUpgraded] = useState<{ from: string; to: string } | null>(null);

  useEffect(() => {
    const candidates = src ? fullSizeCandidates(src) : [];
    if (!src || candidates.length === 0) return;
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
  }, [src]);

  const shown = upgraded && upgraded.from === src ? upgraded.to : src;
  return <PhotoFrame src={shown} {...props} />;
}
