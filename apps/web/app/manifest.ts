import type { MetadataRoute } from "next";

import { palette, SITE_NAME, TAGLINE } from "@/lib/brand";

/**
 * The web app manifest: enough for "Add to home screen" to give makhzan its
 * own name, icon and colours. A step towards installing it (docs/PRODUCT.md);
 * there is deliberately no service worker, so nothing is cached offline.
 *
 * The PNGs are drawn by scripts/brand-icons.mjs.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: SITE_NAME,
    short_name: SITE_NAME,
    description: TAGLINE,
    lang: "en",
    start_url: "/",
    scope: "/",
    display: "standalone",
    theme_color: palette.ground,
    background_color: palette.ground,
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml" },
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
