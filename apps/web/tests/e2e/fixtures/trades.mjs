/**
 * Stub data for the home, trades, trade and category pages.
 *
 * One trade with a real two-level tree (seals-bearings: groups, leaves, an
 * "Other" bucket that must never describe the trade, an empty group that must
 * not become a tile) and products some of which are out of stock, so the
 * hidden count has something to count. Then enough single-category trades to
 * push the total past the eight the home page shows.
 *
 * The shops are made up: the repository is public.
 */

const cat = (domain, slug, name_en, parent, count) => ({
  ref: `${domain}:${slug}`,
  domain,
  slug,
  name_en,
  name_ar: null,
  parent: parent ? `${domain}:${parent}` : null,
  count,
});

export const TRADE_CATEGORIES = [
  cat("seals-bearings", "seals", "Seals & Gaskets", null, 0),
  cat("seals-bearings", "o-rings", "O-Rings", "seals", 400),
  cat("seals-bearings", "oil-seals", "Oil Seals", "seals", 250),
  cat("seals-bearings", "gaskets", "Gaskets", "seals", 90),
  cat("seals-bearings", "seals-other", "Other Seals", "seals", 500),
  cat("seals-bearings", "transmission", "Bearings & Transmission", null, 0),
  cat("seals-bearings", "bearings", "Bearings", "transmission", 300),
  cat("seals-bearings", "couplings", "Couplings", "transmission", 40),
  cat("seals-bearings", "filtration", "Filtration", null, 0),
  cat("seals-bearings", "air-filters", "Air Filters", "filtration", 0),
  cat("piping", "valves", "Butterfly Valves", null, 120),
  cat("timber", "oak", "Oak", null, 90),
  cat("welding", "machines", "Welding Machines", null, 70),
  cat("safety", "gloves", "Gloves", null, 60),
  cat("garden", "mowers", "Mowers & Trimmers", null, 50),
  cat("rigging", "slings", "Slings", null, 25),
  cat("security", "intercoms", "Intercoms", null, 20),
  cat("cleaning", "washers", "Pressure Washers", null, 10),
];

const hit = (
  id,
  category,
  title,
  price,
  { inStock = true, shop = "Delta Seals", shops = 1 } = {},
) => ({
  id,
  domain: "seals-bearings",
  part_number: null,
  title_en: title,
  title_ar: null,
  brand: null,
  category_slug: category,
  category_ref: `seals-bearings:${category}`,
  category_name: TRADE_CATEGORIES.find((c) => c.slug === category)?.name_en ?? null,
  supplier_name: shops > 1 ? null : shop,
  supplier_count: shops,
  offer_count: shops,
  min_price: price,
  max_price: price,
  currency: "EGP",
  in_stock: inStock,
  image: null,
  last_verified_at: Math.floor(Date.now() / 1000) - 3 * 86400,
});

const HITS = [
  hit("sb-1", "o-rings", "NBR O-Ring Kit, 386 Pieces", 450),
  hit("sb-2", "oil-seals", "Oil Seal 35x52x7 NBR", 35, { shops: 2 }),
  hit("sb-3", "bearings", "Deep Groove Ball Bearing 6204-2RS", 60, {
    inStock: false,
    shop: "Nile Bearings",
  }),
  hit("sb-4", "bearings", "Deep Groove Ball Bearing 6205-2RS", 75, {
    inStock: false,
    shop: "Nile Bearings",
  }),
];

/** The search response for this fixture's trade, or null for anything else. */
export function tradeSearch(url) {
  if (url.searchParams.get("domain") !== "seals-bearings") return null;
  const category = url.searchParams.get("category");
  let hits = HITS;
  if (category) hits = hits.filter((h) => h.category_ref === category);
  if (url.searchParams.get("in_stock") === "true") hits = hits.filter((h) => h.in_stock);
  if (Number(url.searchParams.get("min_suppliers") ?? 0) > 1)
    hits = hits.filter((h) => h.supplier_count > 1);
  const limit = Number(url.searchParams.get("limit") ?? 24);
  return {
    query: url.searchParams.get("q") ?? "",
    identifier_query: false,
    total: hits.length,
    limit,
    offset: Number(url.searchParams.get("offset") ?? 0),
    hits: hits.slice(0, limit),
  };
}
