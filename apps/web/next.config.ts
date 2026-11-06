import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for a small runtime
  // image — see apps/web/Dockerfile.
  output: "standalone",

  // Proxy /api/* to the backend over the internal network so the API is never
  // exposed publicly and browser calls stay same-origin (no CORS). The browser
  // hits the relative "/api"; the Next server forwards to API_INTERNAL_URL.
  // Evaluated at server startup, so API_INTERNAL_URL is a runtime env.
  async rewrites() {
    const api = process.env.API_INTERNAL_URL ?? "http://api:8000";
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
};

export default nextConfig;
