/**
 * Server-side API client.
 *
 * Every call here runs on the server during render. The previous app fetched
 * from `useEffect` in client components, which meant the HTML shipped empty —
 * fatal for a discovery product whose value is being found for "LM358 القاهرة".
 *
 * Caching is deliberate rather than uniform. The catalogue moves at the pace of
 * the ingestion cycle (about a week), so taxonomy and supplier profiles are
 * cached for minutes; search is not cached at all, because a filtered query is
 * unique to one visitor and caching it wastes memory to no benefit.
 */

import type { Lang } from "@/lib/i18n";

/**
 * Server-to-server where possible: a server component calling the public URL
 * would round-trip through Next's own rewrite for no reason.
 */
const API_BASE =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Seconds. Long enough to absorb a burst, short enough that a sweep shows up. */
const TAXONOMY_TTL = 300;
const DETAIL_TTL = 120;

export type StockSignal =
  | "in_stock"
  | "low_stock"
  | "out_of_stock"
  | "made_to_order"
  | "unknown";

export type ListingStatus = "active" | "pending_review" | "hidden" | "archived";

export type CategoryRef = {
  /** `domain:slug`. The identity — a bare slug names a category in every
   *  domain that happens to use it. */
  ref: string;
  domain: string;
  slug: string;
  name_en: string;
  name_ar: string | null;
};

export type Category = CategoryRef & {
  /** Parent's `ref`, not its slug. */
  parent: string | null;
  count: number;
};

export type Supplier = {
  id: string;
  slug: string;
  name: string;
  name_ar: string | null;
  area: string | null;
  governorate: string | null;
  website_url: string | null;
};

export type SupplierProfile = Omit<Supplier, "id"> & { listing_count: number };

export type ProductSummary = {
  id: string;
  part_number: string | null;
  title_en: string | null;
  title_ar: string | null;
  brand: string | null;
  image: string | null;
  supplier_count: number;
  offer_count: number;
  min_price: number | null;
  max_price: number | null;
  currency: string;
  in_stock: boolean;
  last_verified_at: string | null;
  category: CategoryRef | null;
};

export type Offer = {
  id: string;
  title_en: string | null;
  title_ar: string | null;
  price: number | null;
  currency: string;
  stock_signal: StockSignal;
  source_url: string | null;
  images: string[];
  last_verified_at: string;
  supplier: Supplier | null;
};

export type Product = ProductSummary & { offers: Offer[] };

export type Listing = {
  id: string;
  /** The canonical product this is an offer of — the way back up to the
   *  comparison. Null for a listing the grouping step left ungrouped. */
  product_id: string | null;
  title_en: string | null;
  title_ar: string | null;
  description_en: string | null;
  description_ar: string | null;
  part_number: string | null;
  brand: string | null;
  price: number | null;
  currency: string;
  unit: string | null;
  stock_signal: StockSignal;
  status: ListingStatus;
  images: string[];
  source_url: string | null;
  last_verified_at: string;
  supplier: Supplier | null;
  category: CategoryRef | null;
};

/** A search hit is the flat Meilisearch document, not a ProductSummary. */
export type SearchHit = {
  id: string;
  domain: string;
  part_number: string | null;
  title_en: string | null;
  title_ar: string | null;
  brand: string | null;
  category_slug: string | null;
  category_ref: string | null;
  category_name: string | null;
  supplier_name: string | null;
  supplier_count: number;
  offer_count: number;
  min_price: number | null;
  max_price: number | null;
  currency: string;
  in_stock: boolean;
  image: string | null;
  last_verified_at: number | null;
};

export type Facets = Record<string, Record<string, number>>;

export type SearchResponse = {
  query: string;
  /** Whether the API treated this as a part number and ranked identifiers
   *  first. Reported by the API so there is one definition of it, not two. */
  identifier_query: boolean;
  total: number | null;
  limit: number;
  offset: number;
  hits: SearchHit[];
  facets?: Facets;
};

export type Stats = { products: number; suppliers: number; categories: number };

export type SearchParams = {
  q?: string;
  category?: string;
  domain?: string;
  inStock?: boolean;
  minPrice?: number;
  maxPrice?: number;
  minSuppliers?: number;
  sort?: string;
  limit?: number;
  offset?: number;
  facets?: boolean;
};

type FetchOptions = { revalidate?: number | false };

async function get<T>(path: string, { revalidate = DETAIL_TTL }: FetchOptions = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    // `false` means "never cache" for a per-visitor query; a number caches it.
    ...(revalidate === false ? { cache: "no-store" as const } : { next: { revalidate } }),
    headers: { accept: "application/json" },
  });
  if (!res.ok) {
    throw new ApiError(res.status, `${path} failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Fetch that turns "not found" into `null` and lets everything else throw.
 *  A missing product is a 404 page; a broken API is an error page. */
async function getOrNull<T>(path: string, options?: FetchOptions): Promise<T | null> {
  try {
    return await get<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

// --------------------------------------------------------------------------- //

export function fetchStats(): Promise<Stats> {
  return get<Stats>("/stats", { revalidate: TAXONOMY_TTL });
}

/** The whole taxonomy, or one vertical's slice of it. */
export function fetchCategories(domain?: string): Promise<Category[]> {
  return get<Category[]>(`/categories${query({ domain })}`, { revalidate: TAXONOMY_TTL });
}

export function searchProducts(params: SearchParams): Promise<SearchResponse> {
  return get<SearchResponse>(
    `/search${query({
      q: params.q ?? "",
      category: params.category,
      domain: params.domain,
      in_stock: params.inStock ? true : undefined,
      min_price: params.minPrice,
      max_price: params.maxPrice,
      min_suppliers: params.minSuppliers,
      sort: params.sort,
      limit: params.limit ?? 24,
      offset: params.offset || undefined,
      facets: params.facets ? true : undefined,
    })}`,
    // A filtered query belongs to one visitor; caching it buys nothing.
    { revalidate: false },
  );
}

export function fetchProduct(id: string): Promise<Product | null> {
  return getOrNull<Product>(`/products/${id}`);
}

export function fetchSimilar(id: string, limit = 8): Promise<ProductSummary[]> {
  return get<ProductSummary[]>(`/products/${id}/similar${query({ limit })}`);
}

export function fetchListing(id: string): Promise<Listing | null> {
  return getOrNull<Listing>(`/listings/${id}`);
}

export function fetchSupplier(slug: string): Promise<SupplierProfile | null> {
  return getOrNull<SupplierProfile>(`/suppliers/${slug}`, { revalidate: TAXONOMY_TTL });
}

export function fetchSupplierListings(
  slug: string,
  { limit = 24, offset = 0 }: { limit?: number; offset?: number } = {},
): Promise<{ total: number; limit: number; offset: number; items: Listing[] } | null> {
  return getOrNull(`/suppliers/${slug}/listings${query({ limit, offset })}`);
}

// --------------------------------------------------------------------------- //
// Display helpers that depend on the shape above
// --------------------------------------------------------------------------- //

/** Titles are supplier prose, so a language may simply be missing. Fall back
 *  rather than render an empty heading. */
export function titleOf(
  item: { title_en: string | null; title_ar: string | null },
  lang: Lang,
): string {
  const preferred = lang === "ar" ? item.title_ar : item.title_en;
  return preferred || item.title_en || item.title_ar || "";
}

export function categoryNameOf(category: CategoryRef, lang: Lang): string {
  return (lang === "ar" ? category.name_ar : category.name_en) || category.name_en;
}

export function supplierNameOf(supplier: Supplier, lang: Lang): string {
  return (lang === "ar" ? supplier.name_ar : supplier.name) || supplier.name;
}
