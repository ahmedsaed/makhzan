/**
 * The results URL contract, shared by every page that lists results (search,
 * trade, category, a shop's own search). The URL is the only state: each
 * filter is a query parameter, so a filtered view can be shared, bookmarked,
 * reached with the back button, and built with JavaScript off.
 *
 *   q              the query text
 *   category       `domain:slug` (a bare slug is accepted, as the API does)
 *   domain         a trade
 *   shop           a supplier slug: search within one shop
 *   in_stock       absent → in stock only (rule C2); `all` → everything.
 *                  `false` is read as `all`, `true` as the default.
 *   min_suppliers  `2` → sold by 2+ shops
 *   min_price, max_price   EGP, on the product's cheapest offer
 *   sort           price:asc | supplier_count:desc | last_verified_at:desc
 *   offset         paging
 *
 * Unknown or malformed values are dropped rather than passed on, so a mangled
 * link shows results instead of an API error.
 */
import type { Facets, SearchParams } from "@/lib/api";
import { withParams } from "@/lib/routes";

export type RawParams = Record<string, string | string[] | undefined>;

export const PAGE_SIZE = 24;

/** What `in_stock` is set to to show out-of-stock results too. */
export const SHOW_ALL_STOCK = "all";

export const SORTS = [
  { value: "", label: "Best match" },
  { value: "price:asc", label: "Price, low first" },
  { value: "supplier_count:desc", label: "Most shops" },
  { value: "last_verified_at:desc", label: "Recently checked" },
] as const;

export type ResultsQuery = {
  q: string;
  category?: string;
  domain?: string;
  shop?: string;
  /** True unless the URL asks for everything: in stock is the default. */
  inStockOnly: boolean;
  minSuppliers?: number;
  minPrice?: number;
  maxPrice?: number;
  sort?: string;
  offset: number;
};

function one(value: string | string[] | undefined): string | undefined {
  const first = Array.isArray(value) ? value[0] : value;
  const trimmed = first?.trim();
  return trimmed ? trimmed : undefined;
}

function positive(value: string | undefined): number | undefined {
  if (value === undefined) return undefined;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : undefined;
}

export function parseResultsQuery(raw: RawParams): ResultsQuery {
  const stock = one(raw.in_stock)?.toLowerCase();
  const minSuppliers = Number.parseInt(one(raw.min_suppliers) ?? "", 10);
  const offset = Number.parseInt(one(raw.offset) ?? "", 10);
  const sort = one(raw.sort);
  let minPrice = positive(one(raw.min_price));
  let maxPrice = positive(one(raw.max_price));
  // A reversed range is a slip, not a request for nothing.
  if (minPrice !== undefined && maxPrice !== undefined && minPrice > maxPrice) {
    [minPrice, maxPrice] = [maxPrice, minPrice];
  }
  return {
    q: one(raw.q) ?? "",
    category: one(raw.category),
    domain: one(raw.domain),
    shop: one(raw.shop),
    inStockOnly: stock !== SHOW_ALL_STOCK && stock !== "false",
    minSuppliers: Number.isFinite(minSuppliers) && minSuppliers > 1 ? minSuppliers : undefined,
    minPrice: minPrice || undefined,
    maxPrice,
    sort: SORTS.some((s) => s.value && s.value === sort) ? sort : undefined,
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

/** The API call for a query. The API's own default is "everything", so in
 *  stock is sent explicitly. */
export function apiParams(query: ResultsQuery): SearchParams {
  return {
    q: query.q,
    category: query.category,
    domain: query.domain,
    shop: query.shop,
    inStock: query.inStockOnly,
    minSuppliers: query.minSuppliers,
    minPrice: query.minPrice,
    maxPrice: query.maxPrice,
    sort: query.sort,
    offset: query.offset || undefined,
    limit: PAGE_SIZE,
    facets: true,
  };
}

/**
 * How many out-of-stock results the in-stock default is hiding, read from the
 * `in_stock` facet of the same search run without the stock filter. Facets
 * are counted over the filtered set, so the main search cannot answer this
 * itself: with the filter on, its facet only ever says "true".
 */
export function hiddenOutOfStock(unfilteredFacets: Facets | undefined): number {
  return unfilteredFacets?.in_stock?.false ?? 0;
}

/** Whether anything beyond the query and the defaults narrows the results. */
export function activeFilterCount(query: ResultsQuery): number {
  return [
    query.category,
    query.domain,
    query.shop,
    query.minSuppliers,
    query.minPrice,
    query.maxPrice,
  ].filter((value) => value !== undefined).length;
}

/** The hrefs every results page needs, built from the current URL so anything
 *  the page does not know about is kept. */
export function resultsLinks(pathname: string, raw: RawParams, query: ResultsQuery) {
  return {
    inStock: withParams(pathname, raw, {
      in_stock: query.inStockOnly ? SHOW_ALL_STOCK : null,
    }),
    showOutOfStock: withParams(pathname, raw, { in_stock: SHOW_ALL_STOCK }),
    twoShops: withParams(pathname, raw, {
      min_suppliers: query.minSuppliers ? null : "2",
    }),
    category: (ref: string | null) => withParams(pathname, raw, { category: ref }),
    clear: (...keys: string[]) =>
      withParams(pathname, raw, Object.fromEntries(keys.map((key) => [key, null]))),
    page: (offset: number) =>
      withParams(pathname, raw, { offset: offset > 0 ? String(offset) : null }),
  };
}

/** Categories from the facet, grouped under their trade; both orders are by
 *  count, largest first. */
export function groupCategoryFacet(facet: Record<string, number> | undefined): {
  domain: string;
  count: number;
  categories: { ref: string; count: number }[];
}[] {
  const trades = new Map<string, { ref: string; count: number }[]>();
  for (const [ref, count] of Object.entries(facet ?? {})) {
    if (count <= 0) continue;
    const domain = ref.includes(":") ? ref.slice(0, ref.indexOf(":")) : "";
    trades.set(domain, [...(trades.get(domain) ?? []), { ref, count }]);
  }
  return [...trades.entries()]
    .map(([domain, categories]) => ({
      domain,
      count: categories.reduce((sum, c) => sum + c.count, 0),
      categories: categories.sort((a, b) => b.count - a.count),
    }))
    .sort((a, b) => b.count - a.count);
}

/** The URL's query as plain pairs, first value of each, empties dropped: what
 *  a GET form carries through as hidden fields. */
export function flatParams(raw: RawParams, omit: string[] = []): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw)) {
    const first = one(value);
    if (first !== undefined && !omit.includes(key)) out[key] = first;
  }
  return out;
}

/** The biggest categories for a query, for the "Top categories" tiles. */
export function topCategories(
  facet: Record<string, number> | undefined,
  limit = 3,
): { ref: string; count: number }[] {
  return Object.entries(facet ?? {})
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([ref, count]) => ({ ref, count }));
}
