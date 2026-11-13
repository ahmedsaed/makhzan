/**
 * Server-side API client.
 *
 * Every call here runs on the server during render. The previous app fetched
 * from `useEffect` in client components, which meant the HTML shipped empty —
 * fatal for a discovery product whose value is being found by search engines.
 *
 * Caching is deliberate rather than uniform. The catalogue moves at the pace of
 * the ingestion cycle (about a week), so taxonomy and supplier profiles are
 * cached for minutes; search is not cached at all, because a filtered query is
 * unique to one visitor and caching it wastes memory to no benefit.
 */

/**
 * Server-to-server where possible: a server component calling the public URL
 * would round-trip through Next's own rewrite for no reason.
 */
const API_BASE =
  process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Seconds. Long enough to absorb a burst, short enough that a sweep shows up.
 *  A page cached as a whole (ISR) passes its own lifetime as `ttl` instead:
 *  the shortest fetch lifetime on a page becomes the page's. */
const TAXONOMY_TTL = 300;
const DETAIL_TTL = 120;
/** The crawler's activity moves once a day, but "read 3 hours ago" should not lag far. */
const ACTIVITY_TTL = 600;

export type StockSignal = "in_stock" | "low_stock" | "out_of_stock" | "made_to_order" | "unknown";

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
  /** The ways to reach the shop an offer row needs. Optional so the page keeps
   *  working against an API that predates it. */
  contact?: ShopReach | null;
};

/** A shop's first phone, WhatsApp and email, as an offer carries them. Numbers
 *  are E.164 (or a five-digit hotline); lib/contact.ts formats them. */
export type ShopReach = {
  phone: string | null;
  whatsapp: string | null;
  email: string | null;
};

/** One more place a shop trades from. */
export type ShopBranch = {
  name: string | null;
  address: string | null;
  area: string | null;
  governorate: string | null;
  phones: string[];
  maps_url: string | null;
};

/**
 * Where some of a shop's contact details came from: "listed" by a person from
 * the shop's own pages, or "read" by the crawler from its structured data, the
 * page, the day, and which fields it supplied.
 */
export type ContactSource = {
  origin: "listed" | "read";
  url: string | null;
  /** An ISO day, "2026-11-03". */
  checked_on: string | null;
  fields: string[];
};

/** How to reach a shop, one value per field, listed values ahead of the crawler's. */
export type ShopContact = {
  phones: string[];
  whatsapp: string | null;
  email: string | null;
  address: string | null;
  area: string | null;
  governorate: string | null;
  maps_url: string | null;
  opening_hours: string[];
  branches: ShopBranch[];
  sources: ContactSource[];
};

/** One shop as `/suppliers` lists it. Counts cover active listings only, and
 *  `last_verified_at` is the newest check among them: a shop the crawler can no
 *  longer reach keeps its listings but stops advancing it. */
export type ShopSummary = {
  slug: string;
  name: string;
  name_ar: string | null;
  website_url: string | null;
  listing_count: number;
  in_stock_count: number;
  last_verified_at: string | null;
  /** Listings per department, largest first. */
  domains: { domain: string; count: number }[];
};

export type SupplierProfile = ShopSummary & {
  area: string | null;
  governorate: string | null;
  /** How to reach it; null when nothing is known. Optional for an older API. */
  contact?: ShopContact | null;
  /** Its largest categories, biggest first. */
  top_categories: { ref: string; name_en: string; name_ar: string | null; count: number }[];
};

/** The shop a product's photo comes from: what the badge on the photo names. */
export type PhotoShop = { slug: string; name: string };

export type ProductSummary = {
  id: string;
  part_number: string | null;
  title_en: string | null;
  title_ar: string | null;
  brand: string | null;
  image: string | null;
  /** Whose photo `image` is. Optional: absent from an API (or a cached
   *  response) older than it, and null until the product's next rebuild. */
  image_shop?: PhotoShop | null;
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
  /** The brand the shop names, when it names one. */
  brand?: string | null;
} & ShopDetailsFields;

/** A file a shop links from its listing: a datasheet, a manual. */
export type ShopDocument = { url: string; label: string | null };

/**
 * What the shop published about its listing beyond title and price: its own
 * spec rows and the files it links. Empty when it published none (most do not).
 * Optional so the page keeps working against an API that predates them.
 */
type ShopDetailsFields = {
  specs?: Record<string, string>;
  documents?: ShopDocument[];
};

/**
 * `offers` are the active ones. Ids are permanent, so a product every shop has
 * withdrawn is still served: `status` "delisted", no offers, and `min_price` /
 * `max_price` / `last_verified_at` as last seen. Optional so the page keeps
 * working against an API that predates them.
 */
export type Product = ProductSummary & {
  offers: Offer[];
  status?: "listed" | "delisted";
  /** When its last offer went. */
  delisted_at?: string | null;
};

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
} & ShopDetailsFields;

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
  /** Whose photo `image` is; optional, as on ProductSummary. */
  image_shop?: PhotoShop | null;
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
  /** Only products with an offer checked within STALE_AFTER_DAYS (C2b). */
  fresh?: boolean;
  minPrice?: number;
  maxPrice?: number;
  minSuppliers?: number;
  /** A supplier slug: search within one shop. */
  shop?: string;
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
 *  A missing product is a 404 page; a broken API is an error page. A 422 is
 *  the API refusing a malformed id (not a UUID): from the visitor's side that
 *  is a page that does not exist, not a fault. */
async function getOrNull<T>(path: string, options?: FetchOptions): Promise<T | null> {
  try {
    return await get<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
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
export function fetchCategories(domain?: string, ttl = TAXONOMY_TTL): Promise<Category[]> {
  return get<Category[]>(`/categories${query({ domain })}`, { revalidate: ttl });
}

export function searchProducts(params: SearchParams): Promise<SearchResponse> {
  return get<SearchResponse>(
    `/search${query({
      q: params.q ?? "",
      category: params.category,
      domain: params.domain,
      in_stock: params.inStock ? true : undefined,
      fresh: params.fresh ? true : undefined,
      min_price: params.minPrice,
      max_price: params.maxPrice,
      min_suppliers: params.minSuppliers,
      shop: params.shop,
      sort: params.sort,
      limit: params.limit ?? 24,
      offset: params.offset || undefined,
      facets: params.facets ? true : undefined,
    })}`,
    // A filtered query belongs to one visitor; caching it buys nothing.
    { revalidate: false },
  );
}

export function fetchProduct(id: string, ttl = DETAIL_TTL): Promise<Product | null> {
  return getOrNull<Product>(`/products/${encodeURIComponent(id)}`, { revalidate: ttl });
}

/**
 * The product an id without a page of its own now leads to, or null: one
 * merged into another product, or one deleted before ids were permanent
 * (docs/decisions/0004-stable-product-ids.md, 0005-url-retirement.md).
 */
export async function fetchProductRedirect(id: string, ttl = DETAIL_TTL): Promise<string | null> {
  const moved = await getOrNull<{ id: string }>(`/products/${encodeURIComponent(id)}/redirect`, {
    revalidate: ttl,
  });
  return moved?.id ?? null;
}

/** Nothing is similar to a product the API does not know (404); a failure throws. */
export async function fetchSimilar(
  id: string,
  limit = 8,
  ttl = DETAIL_TTL,
): Promise<ProductSummary[]> {
  const path = `/products/${encodeURIComponent(id)}/similar${query({ limit })}`;
  return (await getOrNull<ProductSummary[]>(path, { revalidate: ttl })) ?? [];
}

export function fetchListing(id: string, ttl = DETAIL_TTL): Promise<Listing | null> {
  return getOrNull<Listing>(`/listings/${encodeURIComponent(id)}`, { revalidate: ttl });
}

/** Every shop, biggest first — including ones with no active listings, which
 *  the page decides whether to show. */
export function fetchSuppliers(): Promise<ShopSummary[]> {
  return get<ShopSummary[]>("/suppliers", { revalidate: TAXONOMY_TTL });
}

export function fetchSupplier(slug: string, ttl = TAXONOMY_TTL): Promise<SupplierProfile | null> {
  return getOrNull<SupplierProfile>(`/suppliers/${encodeURIComponent(slug)}`, { revalidate: ttl });
}

/**
 * One shop's row of `/crawler/activity`: what the crawler did on its site.
 * Gaps are seconds between consecutive requests over the last 7 days, null
 * when nothing was measured (runs from before pacing was recorded).
 */
export type ShopCrawlActivity = {
  slug: string;
  name: string;
  /** "paused" never comes with a reason, and the page must not invent one. */
  status: "active" | "paused";
  last_read_at: string | null;
  requests_7d: number;
  /** Some run in the window did not record its count: `requests_7d` is a floor. */
  requests_7d_partial: boolean;
  min_gap_s: number | null;
  median_gap_s: number | null;
  /** The last 7 UTC days, oldest first. `requests` is null for a day one of
   *  whose runs did not record its count: never drawn as zero. */
  requests_by_day: { date: string; requests: number | null }[];
  /** Who the latest run said it was, or null before that was recorded. */
  identity: { name: "makhzanbot" | "browser"; signed: boolean } | null;
  /** How many days the last completed full pass took, or null before one. */
  last_cycle_days: number | null;
};

/** One bucket of the week's gaps, all shops together. `max_s` null: open-ended. */
export type GapBucket = { min_s: number; max_s: number | null; count: number };

export type CrawlerActivity = {
  generated_at: string;
  window_days: number;
  shops: ShopCrawlActivity[];
  totals: {
    shops: number;
    shops_active: number;
    shops_read_7d: number;
    requests_7d: number;
    requests_7d_partial: boolean;
    min_gap_s: number | null;
    median_gap_s: number | null;
    /** Null when no gap was measured this week. */
    gap_histogram: GapBucket[] | null;
    robots_txt_honoured: boolean;
  };
  schedule: {
    refresh_hour_utc: number;
    /** Null while the daily sweep is switched off. */
    next_run_at: string | null;
  };
};

/**
 * The crawler's public record, or null when the API cannot give it. Every page
 * that shows it renders without it: /how-we-crawl must stay readable when the
 * catalogue is not, and a shop page is about the shop.
 */
export async function fetchCrawlerActivity(): Promise<CrawlerActivity | null> {
  try {
    return await get<CrawlerActivity>("/crawler/activity", { revalidate: ACTIVITY_TTL });
  } catch {
    return null;
  }
}

/** One sitemap entry's worth of a product. `changed_at` is when what a reader
 *  sees last changed, not the last recheck. */
export type SitemapProduct = {
  id: string;
  title_en: string | null;
  title_ar?: string | null;
  part_number?: string | null;
  changed_at: string;
};

export type SitemapPage = {
  items: SitemapProduct[];
  /** The `after` for the next page; null on the last. */
  next: string | null;
  /** Every listed product; on the first page (no `after`) only. */
  total: number | null;
};

/**
 * Products with an active offer, keyset-paged by id. Not cached: a full page
 * is 50,000 rows, several megabytes, over what Next's data cache keeps per
 * entry; a crawler reads a sitemap seldom enough that each read can ask.
 * The small first page that only counts (`limit=1`) is cached like the taxonomy.
 */
export function fetchSitemapProducts(after: string | null, limit: number): Promise<SitemapPage> {
  return get<SitemapPage>(`/sitemap/products${query({ after: after ?? undefined, limit })}`, {
    revalidate: limit === 1 ? TAXONOMY_TTL : false,
  });
}

/** A shop's listings, in stock first. */
export function fetchSupplierListings(
  slug: string,
  {
    limit = 24,
    offset = 0,
    inStock = false,
  }: { limit?: number; offset?: number; inStock?: boolean } = {},
): Promise<{ total: number; limit: number; offset: number; items: Listing[] } | null> {
  return getOrNull(
    `/suppliers/${encodeURIComponent(slug)}/listings${query({
      in_stock: inStock ? true : undefined,
      limit,
      offset: offset || undefined,
    })}`,
  );
}

// --------------------------------------------------------------------------- //
// Display helpers that depend on the shape above
// --------------------------------------------------------------------------- //

/**
 * The interface is English only, but titles are supplier prose and a few are
 * Arabic only (0.1%). Fall back rather than render an empty heading — and never
 * translate: a listing is evidence about what is on a shop's shelf.
 */
export function titleOf(item: { title_en: string | null; title_ar: string | null }): string {
  return item.title_en || item.title_ar || "";
}

export function categoryNameOf(category: CategoryRef): string {
  return category.name_en;
}

/**
 * A ProductSummary (similar products, rails) in the shape of a search hit, so
 * every list of products renders through ResultRow / ResultCard and carries the
 * same facts (rule C1).
 *
 * A summary does not name its shop; pass `supplierName` when the caller knows it.
 */
export function hitFromSummary(
  product: ProductSummary,
  supplierName: string | null = null,
): SearchHit {
  const verified = product.last_verified_at ? Date.parse(product.last_verified_at) : NaN;
  return {
    id: product.id,
    domain: product.category?.domain ?? "",
    part_number: product.part_number,
    title_en: product.title_en,
    title_ar: product.title_ar,
    brand: product.brand,
    category_slug: product.category?.slug ?? null,
    category_ref: product.category?.ref ?? null,
    category_name: product.category?.name_en ?? null,
    supplier_name: supplierName,
    supplier_count: product.supplier_count,
    offer_count: product.offer_count,
    min_price: product.min_price,
    max_price: product.max_price,
    currency: product.currency,
    in_stock: product.in_stock,
    image: product.image,
    image_shop: product.image_shop ?? null,
    // The index stores epoch seconds; match it.
    last_verified_at: Number.isNaN(verified) ? null : Math.floor(verified / 1000),
  };
}
