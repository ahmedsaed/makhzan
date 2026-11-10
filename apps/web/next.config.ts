import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for a small runtime
  // image — see apps/web/Dockerfile.
  output: "standalone",

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
