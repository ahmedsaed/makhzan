/**
 * The site's own public origin, for everything that must be an absolute URL:
 * canonical links (`metadataBase`) and structured data.
 *
 * From `SITE_URL`, read on the server at runtime (it is not `NEXT_PUBLIC_`, so
 * nothing inlines it at build): one image can serve any host, and the value
 * can never come from a request header a client controls. Unset or malformed,
 * it is the dev server's address.
 */
const DEV_ORIGIN = "http://localhost:3000";

export function siteUrl(): URL {
  try {
    return new URL(process.env.SITE_URL || DEV_ORIGIN);
  } catch {
    return new URL(DEV_ORIGIN);
  }
}

/** An absolute URL for one of the site's own paths. */
export function absoluteUrl(path: string): string {
  return new URL(path, siteUrl()).toString();
}
