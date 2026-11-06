/**
 * Every internal URL is built here, so the language prefix and the category
 * `ref` encoding can never drift between call sites.
 *
 * A category is addressed by `domain:slug`, which becomes two path segments:
 * `electronics:resistors` → `/en/browse/electronics/resistors`. The bare slug is
 * never a URL on its own — `measurement` exists in two domains, and a link built
 * from it silently mixes verticals.
 */

import type { Lang } from "@/lib/i18n";

export type SearchQuery = {
  q?: string;
  category?: string;
  domain?: string;
  inStock?: boolean;
  sort?: string;
  minSuppliers?: number;
  offset?: number;
};

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const out = search.toString();
  return out ? `?${out}` : "";
}

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
  home: (lang: Lang) => `/${lang}`,

  search: (lang: Lang, query: SearchQuery = {}) =>
    `/${lang}/search${qs({
      q: query.q,
      category: query.category,
      domain: query.domain,
      in_stock: query.inStock,
      sort: query.sort,
      min_suppliers: query.minSuppliers,
      // Page zero is the same page as no page. Emitting `offset=0` would give
      // one page two URLs, which is the duplication this rewrite exists to fix.
      offset: query.offset || undefined,
    })}`,

  vertical: (lang: Lang, domain: string) => `/${lang}/browse/${encodeURIComponent(domain)}`,

  /** Browse one category. Falls back to the vertical when handed a bare slug,
   *  which is the honest answer: we cannot tell which domain was meant. */
  category: (lang: Lang, ref: string) => {
    const parts = splitRef(ref);
    if (!parts) return `/${lang}/search${qs({ category: ref })}`;
    return `/${lang}/browse/${encodeURIComponent(parts.domain)}/${encodeURIComponent(parts.slug)}`;
  },

  product: (lang: Lang, id: string) => `/${lang}/products/${id}`,
  listing: (lang: Lang, id: string) => `/${lang}/listings/${id}`,
  supplier: (lang: Lang, slug: string) => `/${lang}/suppliers/${encodeURIComponent(slug)}`,
};

/** The same page in the other language — what the language switch links to. */
export function switchLangPath(pathname: string, to: Lang): string {
  const rest = pathname.replace(/^\/(en|ar)(?=\/|$)/, "");
  return `/${to}${rest}`;
}
