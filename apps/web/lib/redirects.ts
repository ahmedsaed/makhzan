/**
 * Where old URLs went (see proxy.ts): those of the previous, bilingual site,
 * and the "trades" that became "departments" in November 2026.
 *
 *   /en/x, /ar/x                        → /x
 *   /browse/{domain}[/{category}]       → /departments/{domain}[/{category}]
 *   /trades[/{domain}[/{category}]]     → /departments[/{domain}[/{category}]]
 *   /suppliers/{slug}                   → /shops/{slug}
 *
 * each with or without the language prefix, resolved in one hop: every rule
 * is applied in a single pass, so /en/browse/x lands on /departments/x
 * directly, never by way of /trades/x.
 */

const LANG = /^\/(?:en|ar)(?=\/|$)/;

/** The new path for an old one, or null when the path is current. */
export function redirectTarget(pathname: string): string | null {
  const path = (pathname.replace(LANG, "") || "/")
    .replace(/^\/(?:browse|trades)(?=\/|$)/, "/departments")
    .replace(/^\/suppliers(?=\/|$)/, "/shops");
  return path === pathname ? null : path;
}
