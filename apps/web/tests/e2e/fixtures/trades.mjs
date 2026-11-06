/**
 * Stub data for the home, trades, trade and category pages.
 *
 * One trade with a real two-level tree (seals-bearings: groups, leaves, an
 * "Other" bucket that must never describe the trade, an empty group that must
 * not become a tile) and products some of which are out of stock, so the
 * hidden count has something to count. Then enough single-category trades to
 * push the total past the eight the home page shows.
 *
 * The search filters `category` the way the API does since products carry
 * their ancestors (`category_refs`): a group's ref matches everything filed
 * under it. Two ways to make the API fail, for the pages' degraded states: a
 * search in the Gaskets category, and the taxonomy of the `catfail` trade.
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

/** A category's ref and every ancestor's, as the index stores them. */
function ancestry(ref) {
  const refs = [];
  for (let at = ref; at; at = TRADE_CATEGORIES.find((c) => c.ref === at)?.parent ?? null) {
    refs.push(at);
  }
  return refs;
}

function count(hits, key) {
  const out = {};
  for (const hit of hits) out[String(hit[key])] = (out[String(hit[key])] ?? 0) + 1;
  return out;
}

/** `/categories?domain=catfail` fails: the trade pages' "not answering" state. */
export const FAILING_TRADE = "catfail";

/** `{status, body}` for this fixture's trade, or null for anything else. */
export function tradeSearch(url) {
  const params = url.searchParams;
  if (params.get("domain") !== "seals-bearings") return null;
  const category = params.get("category");
  if (category === "seals-bearings:gaskets") {
    return { status: 500, body: { detail: "meilisearch unreachable" } };
  }
  let hits = HITS;
  if (category) hits = hits.filter((h) => ancestry(h.category_ref).includes(category));
  if (params.get("in_stock") === "true") hits = hits.filter((h) => h.in_stock);
  // The API refuses more than 50 (and the page must never send it).
  const minSuppliers = Number(params.get("min_suppliers") ?? 0);
  if (minSuppliers > 50) return { status: 422, body: { detail: "min_suppliers ≤ 50" } };
  if (minSuppliers > 1) hits = hits.filter((h) => h.supplier_count >= minSuppliers);
  const sort = params.get("sort");
  if (sort && !/^(price|last_verified_at|supplier_count):(asc|desc)$/.test(sort)) {
    return { status: 422, body: { detail: "bad sort" } };
  }
  if (sort === "price:asc") hits = [...hits].sort((a, b) => a.min_price - b.min_price);
  const limit = Number(params.get("limit") ?? 24);
  const offset = Number(params.get("offset") ?? 0);
  const body = {
    query: params.get("q") ?? "",
    identifier_query: false,
    total: hits.length,
    limit,
    offset,
    hits: hits.slice(offset, offset + limit),
  };
  if (params.get("facets") === "true") {
    body.facets = {
      domain: count(hits, "domain"),
      category_ref: count(hits, "category_ref"),
      in_stock: count(hits, "in_stock"),
    };
  }
  return { status: 200, body };
}
