/**
 * Every internal URL is built here, so the path scheme and the category `ref`
 * encoding can never drift between call sites.
 *
 * A category is addressed through its department, because category slugs are
 * unique per department only: `tools:measurement` → `/departments/tools/measurement`.
 * The bare slug is never a URL on its own — `measurement` exists in two
 * departments, and a link built from it silently mixes them.
 *
 * "Department" is the reader's word for what the backend calls a domain; the two
 * are the same thing; the web app uses "department" throughout, and keeps
 * `domain` only where it reads the API's field. (It said "trades" until
 * November 2026; lib/redirects.ts sends those URLs here.)
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

  departments: () => "/departments",
  department: (domain: string) => `/departments/${encodeURIComponent(domain)}`,

  /** One category, through its department. Falls back to search when handed a
   *  bare slug, which is the honest answer: we cannot tell which department was
   *  meant. */
  category: (ref: string) => {
    const parts = splitRef(ref);
    if (!parts) return `/search?${new URLSearchParams({ category: ref })}`;
    return `/departments/${encodeURIComponent(parts.domain)}/${encodeURIComponent(parts.slug)}`;
  },

  /** A product's page. With its title, the readable form Google prefers:
   *  `/products/{id}-{words-of-the-title}`. The id alone resolves too, and the
   *  page redirects it (and any stale or wrong slug) to the readable form. */
  product: (id: string, title?: string | null) => `/products/${productParam(id, title)}`,
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

// --------------------------------------------------------------------------- //
// Product URLs: /products/{uuid}-{slug}
// --------------------------------------------------------------------------- //

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
/** Longest slug, in characters; cut at a word. Titles have a long tail (p99 103). */
const MAX_SLUG = 60;

/**
 * Lowercase Latin letters and digits joined by hyphens, from a title: "MG90S
 * Metal Gear Servo (180°)" → "mg90s-metal-gear-servo-180". Empty for a title
 * with no Latin text (an Arabic one): such a product keeps the bare id.
 */
export function slugify(title: string | null | undefined): string {
  const words = (title ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .match(/[a-z0-9]+/g);
  if (!words) return "";
  let slug = "";
  for (const word of words) {
    const next = slug ? `${slug}-${word}` : word;
    if (next.length > MAX_SLUG) break;
    slug = next;
  }
  return slug || words[0].slice(0, MAX_SLUG);
}

/**
 * The path segment for a product. Only a UUID id takes a slug: the id is
 * then a fixed shape at the front and `productIdFrom` can always split it
 * off again. Any other id (test fixtures) is used as it is.
 */
export function productParam(id: string, title?: string | null): string {
  const slug = UUID.test(id) && id.length === 36 ? slugify(title) : "";
  return slug ? `${id}-${slug}` : encodeURIComponent(id);
}

/** The product id in a path segment, slug or not. */
export function productIdFrom(param: string): string {
  const decoded = decodeURIComponent(param);
  const match = decoded.match(UUID);
  return match ? match[0] : decoded;
}
