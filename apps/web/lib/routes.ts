/**
 * Every internal URL is built here, so the path scheme and the category `ref`
 * encoding can never drift between call sites.
 *
 * A category is addressed through its trade, because category slugs are unique
 * per trade only: `tools:measurement` → `/trades/tools/measurement`. The bare
 * slug is never a URL on its own — `measurement` exists in two trades, and a
 * link built from it silently mixes them.
 *
 * "Trade" is the reader's word for what the backend calls a domain; the two are
 * the same thing, and only URLs and copy use the new name.
 */

/** Split `domain:slug` into its parts. Returns null for a bare slug, which is
 *  not addressable. */
export function splitRef(ref: string): { domain: string; slug: string } | null {
  const index = ref.indexOf(":");
  if (index <= 0 || index === ref.length - 1) return null;
  return { domain: ref.slice(0, index), slug: ref.slice(index + 1) };
}

export function joinRef(domain: string, slug: string): string {
  return `${domain}:${slug}`;
}

export const routes = {
  home: () => "/",

  trades: () => "/trades",
  trade: (domain: string) => `/trades/${encodeURIComponent(domain)}`,

  /** One category, through its trade. Falls back to search when handed a bare
   *  slug, which is the honest answer: we cannot tell which trade was meant. */
  category: (ref: string) => {
    const parts = splitRef(ref);
    if (!parts) return `/search?${new URLSearchParams({ category: ref })}`;
    return `/trades/${encodeURIComponent(parts.domain)}/${encodeURIComponent(parts.slug)}`;
  },

  product: (id: string) => `/products/${encodeURIComponent(id)}`,
  shops: () => "/shops",
  shop: (slug: string) => `/shops/${encodeURIComponent(slug)}`,
  howWeCrawl: () => "/how-we-crawl",
  forSuppliers: () => "/for-suppliers",
};

/**
 * The same URL with some query parameters set or removed — what every filter
 * chip, sort option and "show out of stock" link is built from.
 *
 * `null` removes a parameter. Paging is dropped unless explicitly set: a page
 * number means nothing once the result set it counted has changed.
 */
export function withParams(
  pathname: string,
  current: URLSearchParams | Record<string, string | string[] | undefined>,
  updates: Record<string, string | null>,
): string {
  const params =
    current instanceof URLSearchParams ? new URLSearchParams(current) : fromRecord(current);
  if (!("offset" in updates)) params.delete("offset");
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === "") params.delete(key);
    else params.set(key, value);
  }
  const out = params.toString();
  return out ? `${pathname}?${out}` : pathname;
}

function fromRecord(record: Record<string, string | string[] | undefined>): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(record)) {
    if (value === undefined) continue;
    for (const one of Array.isArray(value) ? value : [value]) params.append(key, one);
  }
  return params;
}
