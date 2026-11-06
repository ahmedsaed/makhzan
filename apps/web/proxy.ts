/**
 * Every page lives under a language prefix, so anything arriving without one is
 * redirected rather than served. That keeps a single canonical URL per page —
 * which is the whole point of moving language out of React state.
 *
 * Next 16 renamed this convention from `middleware` to `proxy`.
 *
 * Arabic is offered when the browser asks for it first; English otherwise. The
 * redirect is 307, not 308: a visitor's language preference is not a permanent
 * property of the URL, and a cached permanent redirect would pin the wrong one.
 */
import { NextResponse, type NextRequest } from "next/server";

import { LANGS, preferredLang } from "@/lib/i18n";

const PREFIXED = new RegExp(`^/(${LANGS.join("|")})(/|$)`);

export default function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (PREFIXED.test(pathname)) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = `/${preferredLang(request.headers.get("accept-language"))}${pathname === "/" ? "" : pathname}`;
  return NextResponse.redirect(url, 307);
}

export const config = {
  // Everything except Next internals, the API proxy, and files with an extension.
  matcher: ["/((?!api|_next|.*\\..*).*)"],
};
