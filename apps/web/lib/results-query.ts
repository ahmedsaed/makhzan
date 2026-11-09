/**
 * The results URL contract, shared by every page that lists results (search,
 * department, category, a shop's own search). The URL is the only state: each
 * filter is a query parameter, so a filtered view can be shared, bookmarked,
 * reached with the back button, and built with JavaScript off.
 *
 *   q              the query text
 *   category       `domain:slug` (a bare slug is accepted, as the API does)
 *   domain         a department
 *   shop           a supplier slug: search within one shop
 *   in_stock       absent → in stock only (rule C2); `all` → everything.
 *                  `false` is read as `all`, `true` as the default.
 *   stale          absent → recently checked only, i.e. stale products hidden
 *                  (rule C2b, STALE_AFTER_DAYS in lib/freshness.ts); `all` →
 *                  everything. `hide` asks for the filter where the page's
 *                  own default is to show them: a stale shop's own page,
 *                  which shows its products anyway (see `parseResultsQuery`).
 *   min_suppliers  `2` → sold by 2+ shops (2..50, the API's cap)
 *   min_price, max_price   EGP, on the product's cheapest offer
 *   sort           price:asc | supplier_count:desc | last_verified_at:desc
 *   offset         paging
 *
 * Unknown or malformed values are dropped rather than passed on, so a mangled
 * link shows results instead of an API error.
 */
import { searchProducts, type Facets, type SearchParams, type SearchResponse } from "@/lib/api";
import { formatCount, plural } from "@/lib/format";
import { withParams } from "@/lib/routes";

export type RawParams = Record<string, string | string[] | undefined>;

export const PAGE_SIZE = 24;

/** The API refuses `min_suppliers` above this; a link asking for more is
 *  clamped to it rather than turned into an error. */
export const MAX_MIN_SUPPLIERS = 50;

/** What `in_stock` is set to to show out-of-stock results too. */
export const SHOW_ALL_STOCK = "all";

/** What `stale` is set to to show out-of-date results too (C2b)… */
export const SHOW_STALE = "all";
/** …and to hide them on a page that shows them by default. */
export const HIDE_STALE = "hide";

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
  /** True unless the URL asks for everything: recently checked is the default
   *  (C2b), except on a stale shop's own page. */
  freshOnly: boolean;
  /** What a URL without `stale` means on this page, so a link can toggle the
   *  filter by adding or removing the parameter rather than pinning it. */
  freshByDefault: boolean;
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

/**
 * The URL's query, defaults filled in.
 *
 * `freshByDefault` is false only on a shop's own page when that shop's data is
 * itself stale: there the visitor asked for that shop, the page already says
 * its data is old (F3), and hiding stale products would hide nearly all of
 * them, or worse, show just the few that a fresher shop also sells.
 */
export function parseResultsQuery(
  raw: RawParams,
  { freshByDefault = true }: { freshByDefault?: boolean } = {},
): ResultsQuery {
  const stock = one(raw.in_stock)?.toLowerCase();
  const stale = one(raw.stale)?.toLowerCase();
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
    freshOnly: stale === SHOW_STALE ? false : stale === HIDE_STALE ? true : freshByDefault,
    freshByDefault,
    minSuppliers:
      Number.isFinite(minSuppliers) && minSuppliers > 1
        ? Math.min(minSuppliers, MAX_MIN_SUPPLIERS)
        : undefined,
    minPrice: minPrice || undefined,
    maxPrice,
    sort: SORTS.some((s) => s.value && s.value === sort) ? sort : undefined,
    offset: Number.isFinite(offset) && offset > 0 ? offset : 0,
  };
}

/** The API call for a query. The API's own default is "everything", so in
 *  stock and recently checked are sent explicitly. */
export function apiParams(query: ResultsQuery): SearchParams {
  return {
    q: query.q,
    category: query.category,
    domain: query.domain,
    shop: query.shop,
    inStock: query.inStockOnly,
    fresh: query.freshOnly,
    minSuppliers: query.minSuppliers,
    minPrice: query.minPrice,
    maxPrice: query.maxPrice,
    sort: query.sort,
    offset: query.offset || undefined,
    limit: PAGE_SIZE,
    facets: true,
  };
}

export type ResultsData = {
  /** Null when the API failed: the page says so instead of erroring. */
  result: SearchResponse | null;
  /** The same search without the stock filter (freshness kept), for how many
   *  out-of-stock results one click on "more out of stock" adds. */
  unfiltered: SearchResponse | null;
  /** The same search without either default filter, for how many out-of-date
   *  results the freshness default hides (and the overlap of the two). */
  everything?: SearchResponse | null;
  /** The same search without the picked category, for the category list. */
  wide: SearchResponse | null;
};

/**
 * Every search a results page needs, run together, each failure caught so a
 * broken API degrades the page instead of taking it down.
 *
 * `baseCategory` is the category the page itself is (a category page's own);
 * the category list is counted against that, not against the whole catalogue.
 */
export async function fetchResults(
  query: ResultsQuery,
  { baseCategory }: { baseCategory?: string } = {},
): Promise<ResultsData> {
  const params = apiParams(query);
  // Counts only: one hit is the least the API will return.
  const countOnly = { limit: 1, offset: undefined, sort: undefined };
  const [result, unfiltered, everything, wide] = await Promise.all([
    searchProducts(params).catch(() => null),
    // Facets are counted over the filtered set, so how many the in-stock
    // default hides needs the same search without it.
    query.inStockOnly
      ? searchProducts({ ...params, ...countOnly, inStock: false }).catch(() => null)
      : null,
    // And how many the freshness default hides. Both filters dropped, not just
    // freshness: its `in_stock` facet then splits what is hidden into the part
    // one click shows (in stock, or anything when stock is not filtered) and
    // the part only out of stock *and* out of date, which neither link alone
    // would bring back (see `hiddenCounts`).
    query.freshOnly
      ? searchProducts({ ...params, ...countOnly, inStock: false, fresh: false }).catch(
          () => null,
        )
      : null,
    // Likewise the category list: with one picked, the main search's facet
    // holds only that one, and the others must stay pickable.
    query.category !== baseCategory
      ? searchProducts({ ...params, ...countOnly, category: baseCategory }).catch(() => null)
      : null,
  ]);
  return { result, unfiltered, everything, wide: wide ?? result };
}

/** The toolbar's count. With the default stock filter on it says so, so a
 *  header's catalogue count and this one never look like a contradiction. */
export function countText(total: number, inStockOnly: boolean): string {
  return inStockOnly ? `${formatCount(total)} in stock` : plural(total, "result");
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

/** How many results a response counts, read off its `in_stock` facet (every
 *  document has one) so it is counted the same way as the hidden counts it is
 *  compared with; the estimated total when the facet is missing. */
function facetTotal(response: SearchResponse | null | undefined): number {
  const facet = response?.facets?.in_stock;
  if (facet) return (facet.true ?? 0) + (facet.false ?? 0);
  return response?.total ?? 0;
}

export type HiddenCounts = {
  /** Out of stock but recently checked: what "N more out of stock" adds. */
  outOfStock: number;
  /** Out of date, and in stock when stock is filtered: what "N more out of
   *  date" adds. */
  stale: number;
  /** Out of stock *and* out of date, hidden by both filters at once: neither
   *  link alone shows these, so they are in neither count. */
  both: number;
};

/**
 * What the defaults (in stock, C2; recently checked, C2b) hide, split so every
 * number on the page is exactly what its one click adds. The two overlap: a
 * product can be both out of stock and out of date. Counting it under both
 * links would promise it twice; counting it under either would promise a click
 * that does not show it. So it is counted apart, and offered on its own only
 * when it is all there is (an empty page's "show everything").
 */
export function hiddenCounts(query: ResultsQuery, data: ResultsData): HiddenCounts {
  const outOfStock = query.inStockOnly ? hiddenOutOfStock(data.unfiltered?.facets) : 0;
  if (!query.freshOnly || !data.everything) return { outOfStock, stale: 0, both: 0 };
  const shown = facetTotal(data.result);
  if (!query.inStockOnly) {
    return { outOfStock, stale: Math.max(0, facetTotal(data.everything) - shown), both: 0 };
  }
  const all = data.everything.facets?.in_stock;
  return {
    outOfStock,
    stale: Math.max(0, (all?.true ?? 0) - shown),
    both: Math.max(0, (all?.false ?? 0) - outOfStock),
  };
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
    /** The "Recently checked" chip: turns the freshness filter (C2b) off or on. */
    fresh: withParams(pathname, raw, {
      stale: query.freshOnly === query.freshByDefault
        ? query.freshByDefault
          ? SHOW_STALE
          : HIDE_STALE
        : null,
    }),
    showStale: withParams(pathname, raw, { stale: query.freshByDefault ? SHOW_STALE : null }),
    /** Both defaults off: for a page whose every match is hidden by both. */
    showEverything: withParams(pathname, raw, {
      in_stock: SHOW_ALL_STOCK,
      stale: query.freshByDefault ? SHOW_STALE : null,
    }),
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

/** Categories from the facet, grouped under their department; both orders are by
 *  count, largest first. */
export function groupCategoryFacet(facet: Record<string, number> | undefined): {
  domain: string;
  count: number;
  categories: { ref: string; count: number }[];
}[] {
  const departments = new Map<string, { ref: string; count: number }[]>();
  for (const [ref, count] of Object.entries(facet ?? {})) {
    if (count <= 0) continue;
    const domain = ref.includes(":") ? ref.slice(0, ref.indexOf(":")) : "";
    departments.set(domain, [...(departments.get(domain) ?? []), { ref, count }]);
  }
  return [...departments.entries()]
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
