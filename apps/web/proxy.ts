/**
 * Permanent redirects from the URLs of the previous, bilingual site, and from
 * /trades (renamed /departments in November 2026) — the mapping is in
 * lib/redirects.ts.
 *
 * Those URLs were shared, bookmarked and indexed, and each still has an
 * equivalent, so they redirect rather than 404. 308, permanent, because the
 * language prefix and the old names are gone for good and search engines
 * should move their index over.
 *
 * `/listings/{id}` needs an API call to find its product, so the page at
 * app/listings/[id] answers that one; a prefixed `/en/listings/{id}` loses its
 * prefix here first.
 *
 * Next 16 renamed this convention from `middleware` to `proxy`.
 */
import { NextResponse, type NextRequest } from "next/server";

import { redirectTarget } from "@/lib/redirects";

export default function proxy(request: NextRequest) {
  const target = redirectTarget(request.nextUrl.pathname);
  if (target === null) return NextResponse.next();

  // Keeps the query string: /en/search?q=ESP32 must still search for ESP32.
  const url = request.nextUrl.clone();
  url.pathname = target;
  return NextResponse.redirect(url, 308);
}

export const config = {
  // Only the old prefixes; every current URL skips the proxy entirely.
  matcher: [
    "/en",
    "/en/:path*",
    "/ar",
    "/ar/:path*",
    "/browse",
    "/browse/:path*",
    "/trades",
    "/trades/:path*",
    "/suppliers",
    "/suppliers/:path*",
  ],
};
