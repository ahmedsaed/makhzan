import path from "node:path";

import type { NextConfig } from "next";

import { PAGE_MAX_AGE } from "./cache-handler.mjs";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for a small runtime
  // image — see apps/web/Dockerfile.
  output: "standalone",

  // Product pages are cached (ISR, revalidate 6 h). A copy over a day old is
  // never served: the cache handler ignores it and later deletes it, and
  // `expireTime` tells a CDN the same (s-maxage=21600,
  // stale-while-revalidate=64800). A day, because the page says "checked N
  // days ago" and folds offers unchecked for 45 days, both computed when the
  // copy was rendered; a day old, they are off by at most one. The pages are
  // written to .next/server/app, inside the container rather than the
  // web_cache volume, so a new image starts with none.
  cacheHandler: path.resolve("cache-handler.mjs"),
  expireTime: PAGE_MAX_AGE,

  // The link-preview cards read their fonts from disk (lib/og.tsx), by a path
  // the bundler cannot follow; without this the standalone image ships
  // without them and every card falls back to the renderer's own face.
  outputFileTracingIncludes: {
    "/**": ["./assets/fonts/*.ttf"],
  },

  // Proxy /api/* to the backend over the internal network so the API is never
  // exposed publicly and browser calls stay same-origin (no CORS). The browser
  // hits the relative "/api"; the Next server forwards to API_INTERNAL_URL.
  // Evaluated at server startup, so API_INTERNAL_URL is a runtime env.
  async rewrites() {
    const api = process.env.API_INTERNAL_URL ?? "http://api:8000";
    return [
      { source: "/api/:path*", destination: `${api}/:path*` },
      // The sitemap index, at the address robots.txt names. `generateSitemaps`
      // (app/sitemap.ts) serves only /sitemap/{id}.xml, yet still claims
      // /sitemap.xml, so the index cannot be a route there; see
      // app/sitemap-index.xml/route.ts.
      { source: "/sitemap.xml", destination: "/sitemap-index.xml" },
      // The crawler's Web Bot Auth key directory, served and signed by the API
      // (apps/api/app/routers/wellknown.py). A rewrite, not a redirect: a
      // verifier (Cloudflare, Shopify) requires a plain 200 at exactly this
      // path, on the origin our Signature-Agent header names.
      {
        source: "/.well-known/http-message-signatures-directory",
        destination: `${api}/.well-known/http-message-signatures-directory`,
      },
    ];
  },
};

export default nextConfig;
