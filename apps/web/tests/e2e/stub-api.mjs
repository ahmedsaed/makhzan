/**
 * A stand-in for apps/api, used only by the Playwright suite.
 *
 * The pages fetch on the *server*, so a browser-level route interceptor cannot
 * see those requests — the stub has to be a real HTTP server the Next process
 * points at. That is a feature rather than a workaround: these tests are about
 * the frontend's behaviour (routing, redirects, server rendering, working
 * without JavaScript), and the API has tests of its own. Keeping them separate
 * means the suite needs no Postgres, no Meilisearch and no Python.
 *
 * The payloads are shaped exactly like the real ones, including the awkward
 * parts the UI has to survive: a product with no photo, an offer with no price,
 * an Arabic title alongside a Latin part number, a withdrawn listing, and one
 * the grouping step never attached to a product.
 */
import { createServer } from "node:http";

const PORT = Number(process.env.STUB_PORT ?? 8787);

const CATEGORIES = [
  {
    ref: "electronics:components",
    domain: "electronics",
    slug: "components",
    name_en: "Components",
    name_ar: "مكونات",
    parent: null,
    count: 0,
  },
  {
    ref: "electronics:ics",
    domain: "electronics",
    slug: "ics",
    name_en: "Integrated Circuits",
    name_ar: "دوائر متكاملة",
    parent: "electronics:components",
    count: 120,
  },
  {
    ref: "electronics:resistors",
    domain: "electronics",
    slug: "resistors",
    name_en: "Resistors",
    name_ar: "مقاومات",
    parent: "electronics:components",
    count: 80,
  },
  {
    // The collision the whole ref scheme exists for: the same slug in another
    // domain is a different category.
    ref: "tools:measurement",
    domain: "tools",
    slug: "measurement",
    name_en: "Measuring Tools",
    name_ar: "أدوات قياس",
    parent: null,
    count: 30,
  },
];

const HIT = {
  id: "prod-1",
  domain: "electronics",
  part_number: "ESP32-WROOM-32",
  title_en: "ESP32-WROOM-32 DevKit V1",
  title_ar: "لوحة تطوير ESP32-WROOM-32",
  brand: "Espressif",
  category_slug: "ics",
  category_ref: "electronics:ics",
  category_name: "Integrated Circuits",
  supplier_name: "Shop A",
  supplier_count: 3,
  offer_count: 3,
  min_price: 185,
  max_price: 210,
  currency: "EGP",
  in_stock: true,
  image: null,
  last_verified_at: 1_760_000_000,
};

const HIT_2 = {
  ...HIT,
  id: "prod-2",
  part_number: "LM358N",
  title_en: "LM358N Dual Op-Amp",
  title_ar: null,
  min_price: 12.5,
  supplier_count: 1,
  supplier_name: "Shop B",
};

const SUPPLIER = {
  id: "sup-1",
  slug: "shop-a",
  name: "Shop A",
  name_ar: "متجر أ",
  area: "Bab El Louk",
  governorate: "Cairo",
  website_url: "https://shop-a.test",
};

const PRODUCT = {
  id: "prod-1",
  part_number: "ESP32-WROOM-32",
  title_en: "ESP32-WROOM-32 DevKit V1",
  title_ar: "لوحة تطوير ESP32-WROOM-32",
  brand: "Espressif",
  image: null,
  supplier_count: 3,
  offer_count: 3,
  min_price: 185,
  max_price: 210,
  currency: "EGP",
  in_stock: true,
  last_verified_at: "2026-09-01T10:00:00Z",
  category: CATEGORIES[1],
  offers: [
    {
      id: "off-1",
      title_en: "ESP32 DevKit",
      title_ar: null,
      price: 185,
      currency: "EGP",
      stock_signal: "in_stock",
      source_url: "https://shop-a.test/p/esp32",
      images: [],
      last_verified_at: "2026-09-01T10:00:00Z",
      supplier: SUPPLIER,
    },
    {
      id: "off-2",
      title_en: "ESP32 DevKit",
      title_ar: null,
      // Price on request must stay visible and never sort as free.
      price: null,
      currency: "EGP",
      stock_signal: "unknown",
      source_url: "https://shop-b.test/p/esp32",
      images: [],
      last_verified_at: "2026-08-20T10:00:00Z",
      supplier: { ...SUPPLIER, id: "sup-2", slug: "shop-b", name: "Shop B" },
    },
  ],
};

const LISTING = {
  id: "listing-1",
  product_id: "prod-1",
  title_en: "ESP32-WROOM-32 DevKit V1",
  title_ar: "لوحة تطوير ESP32-WROOM-32",
  description_en: "Dual-core module with WiFi and Bluetooth.",
  description_ar: null,
  part_number: "ESP32-WROOM-32",
  brand: "Espressif",
  price: 185,
  currency: "EGP",
  unit: "piece",
  stock_signal: "in_stock",
  status: "active",
  images: [],
  source_url: "https://shop-a.test/p/esp32",
  last_verified_at: "2026-09-01T10:00:00Z",
  supplier: SUPPLIER,
  category: CATEGORIES[1],
};

const WITHDRAWN = { ...LISTING, id: "listing-gone", status: "archived", source_url: null };

function search(url) {
  const q = url.searchParams.get("q") ?? "";
  const domain = url.searchParams.get("domain");
  const minSuppliers = Number(url.searchParams.get("min_suppliers") ?? 0);

  let hits = [HIT, HIT_2];
  if (q.toLowerCase().includes("nothing")) hits = [];
  if (domain === "tools") hits = [];
  if (minSuppliers > 1) hits = [HIT];

  const body = {
    query: q,
    // "ESP32" and "LM358" are identifier-shaped; a phrase is not.
    identifier_query: /^[a-z0-9][a-z0-9-]*$/i.test(q.trim()) && q.trim().length > 0,
    total: hits.length,
    limit: Number(url.searchParams.get("limit") ?? 24),
    offset: Number(url.searchParams.get("offset") ?? 0),
    hits,
  };
  if (url.searchParams.get("facets") === "true") {
    body.facets = {
      domain: { electronics: 2, tools: 1 },
      category_ref: { "electronics:ics": 2 },
      in_stock: { true: 2 },
    };
  }
  return body;
}

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const send = (status, body) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  };

  const path = url.pathname;
  if (path === "/health") return send(200, { status: "ok" });
  if (path === "/stats") return send(200, { products: 57207, suppliers: 8, categories: 249 });
  if (path === "/categories") {
    const domain = url.searchParams.get("domain");
    return send(200, domain ? CATEGORIES.filter((c) => c.domain === domain) : CATEGORIES);
  }
  if (path === "/search") return send(200, search(url));
  if (path === "/products/prod-1/similar") {
    // A ProductSummary: no offers key at all, which is the point of the shape.
    const summary = { ...PRODUCT };
    delete summary.offers;
    return send(200, [
      { ...summary, id: "prod-2", title_en: "LM358N Dual Op-Amp", title_ar: null, min_price: 12.5 },
    ]);
  }
  if (path === "/products/prod-1") return send(200, PRODUCT);
  if (path === "/listings/listing-1") return send(200, LISTING);
  // The offers are listings too, so opening one has somewhere to land.
  if (path === "/listings/off-1") return send(200, { ...LISTING, id: "off-1" });
  if (path === "/listings/off-2")
    return send(200, { ...LISTING, id: "off-2", price: null, supplier: { ...SUPPLIER, id: "sup-2", slug: "shop-b", name: "Shop B" } });
  if (path === "/listings/listing-gone") return send(200, WITHDRAWN);
  if (path === "/listings/listing-orphan")
    return send(200, { ...LISTING, id: "listing-orphan", product_id: null });
  if (path === "/suppliers/shop-a") return send(200, { ...SUPPLIER, listing_count: 120 });
  if (path === "/suppliers/shop-a/listings")
    return send(200, { total: 1, limit: 24, offset: 0, items: [LISTING] });

  return send(404, { detail: "not found" });
});

server.listen(PORT, () => {
  process.stdout.write(`stub api on ${PORT}\n`);
});
