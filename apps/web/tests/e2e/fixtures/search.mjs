/**
 * Search fixtures for the results page: a small catalogue the stub filters,
 * facets and pages the way the API does, so in stock by default, the hidden
 * count, the chips, the filters and paging can be exercised end to end.
 *
 * Only the queries below are answered here; anything else falls through to
 * the stub's own search. Shops are fictional (the repo is public).
 *
 *   relay      36 products: 30 in stock, 6 not; three categories; some sold
 *              by 2+ shops; some at Shop A
 *   obsolete   2 products, neither in stock
 *   capacitor  12 products, out of stock and out of date in every mix (C2b):
 *              4 in stock and fresh, 4 in stock and stale, 2 out of stock and
 *              fresh, 2 out of stock and stale
 *   dusty      3 products in stock, all stale
 *   ancient    3 products, all out of stock and stale
 *   searchfail the API failing
 */

const NOW = Math.floor(Date.now() / 1000);
const DAY = 86_400;

const CATEGORY = [
  { ref: "electronics:ics", name: "Integrated Circuits" },
  { ref: "electronics:resistors", name: "Resistors" },
  { ref: "tools:measurement", name: "Measuring Tools" },
];

function relay(index) {
  const category = CATEGORY[index % 5 === 0 ? 2 : index % 2];
  const shops = index % 4 === 0 ? ["shop-a", "shop-c"] : [index % 3 === 0 ? "shop-a" : "shop-c"];
  return {
    id: `relay-${index}`,
    domain: category.ref.split(":")[0],
    part_number: null,
    title_en: `Relay module ${index} channel ${index % 2 ? "5V" : "12V"}`,
    title_ar: null,
    brand: null,
    category_slug: category.ref.split(":")[1],
    category_ref: category.ref,
    category_name: category.name,
    supplier_name: shops.length > 1 ? null : shops[0] === "shop-a" ? "Shop A" : "Shop C",
    supplier_slugs: shops,
    supplier_count: shops.length,
    offer_count: shops.length,
    min_price: 40 + index * 10,
    max_price: shops.length > 1 ? 60 + index * 10 : 40 + index * 10,
    currency: "EGP",
    in_stock: index < 30,
    image: null,
    // Quiet and muted ages; none stale, which "capacitor" covers (C2b).
    last_verified_at: NOW - (index % 3) * 20 * DAY,
  };
}

/** Stale is more than 45 whole days; 76 is what the unreachable shops are. */
const STALE_AGE = 76 * DAY;

function capacitor(index) {
  return {
    ...relay(index),
    id: `capacitor-${index}`,
    title_en: `Capacitor ${index} ${index < 8 ? "in stock" : "gone"} ${index % 2 ? "old" : "new"}`,
    in_stock: index < 8,
    last_verified_at: index % 2 ? NOW - STALE_AGE : NOW - 2 * DAY,
  };
}

const CATALOGUE = {
  relay: Array.from({ length: 36 }, (_, index) => relay(index)),
  obsolete: [relay(31), relay(32)].map((hit) => ({ ...hit, title_en: `Obsolete ${hit.title_en}` })),
  capacitor: Array.from({ length: 12 }, (_, index) => capacitor(index)),
  dusty: [1, 3, 5].map((index) => ({ ...capacitor(index), title_en: `Dusty ${index}` })),
  ancient: [9, 11, 13].map((index) => ({
    ...capacitor(index),
    in_stock: false,
    title_en: `Ancient ${index}`,
  })),
};

/** What the API's `fresh` filter keeps: checked within 45 whole days. */
const fresh = (hit) => Math.floor(Date.now() / 1000) - hit.last_verified_at < 46 * DAY;

function count(hits, key) {
  const out = {};
  for (const hit of hits) out[String(hit[key])] = (out[String(hit[key])] ?? 0) + 1;
  return out;
}

/** `{status, body}` for a query this file owns, or null. */
export function searchFixture(url) {
  const params = url.searchParams;
  const q = (params.get("q") ?? "").trim().toLowerCase();
  if (q === "searchfail") return { status: 500, body: { detail: "meilisearch unreachable" } };
  const all = CATALOGUE[q];
  if (!all) return null;

  const minPrice = params.get("min_price");
  const maxPrice = params.get("max_price");
  let hits = all.filter(
    (hit) =>
      (params.get("in_stock") !== "true" || hit.in_stock) &&
      (params.get("fresh") !== "true" || fresh(hit)) &&
      (!params.get("category") || hit.category_ref === params.get("category")) &&
      (!params.get("domain") || hit.domain === params.get("domain")) &&
      (!params.get("shop") || hit.supplier_slugs.includes(params.get("shop"))) &&
      hit.supplier_count >= Number(params.get("min_suppliers") ?? 0) &&
      (minPrice === null || hit.min_price >= Number(minPrice)) &&
      (maxPrice === null || hit.min_price <= Number(maxPrice)),
  );
  const sort = params.get("sort");
  if (sort === "price:asc") hits = [...hits].sort((a, b) => a.min_price - b.min_price);
  else hits = [...hits].sort((a, b) => b.min_price - a.min_price);

  const limit = Number(params.get("limit") ?? 24);
  const offset = Number(params.get("offset") ?? 0);
  const body = {
    query: params.get("q"),
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
