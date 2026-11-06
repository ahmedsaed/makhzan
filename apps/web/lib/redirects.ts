/**
 * Where the URLs of the previous, bilingual site went (see proxy.ts).
 *
 *   /en/x, /ar/x                        → /x
 *   /browse/{trade}[/{category}]        → /trades/{trade}[/{category}]
 *   /suppliers/{slug}                   → /shops/{slug}
 *
 * each with or without the language prefix, resolved in one hop.
 */

const LANG = /^\/(?:en|ar)(?=\/|$)/;

/** The new path for an old one, or null when the path is current. */
export function redirectTarget(pathname: string): string | null {
  const path = (pathname.replace(LANG, "") || "/")
    .replace(/^\/browse(?=\/|$)/, "/trades")
    .replace(/^\/suppliers(?=\/|$)/, "/shops");
  return path === pathname ? null : path;
}
