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
import { readFileSync } from "node:fs";
import { createServer } from "node:http";

import { crawlerActivity } from "./fixtures/crawler.mjs";
import { phase2Fixture } from "./fixtures/phase2.mjs";
import { productFixture } from "./fixtures/product.mjs";
import { photoShopRoute } from "./fixtures/photo-shop.mjs";
import { searchFixture } from "./fixtures/search.mjs";
import { shopName, shopRoute } from "./fixtures/shops.mjs";
import { FAILING_DEPARTMENT, DEPARTMENT_CATEGORIES, departmentSearch } from "./fixtures/departments.mjs";

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

/** A real PNG to stand in for a shop's product photo: the app's own icon. */
const PHOTO_PNG = readFileSync(new URL("../../public/icon-192.png", import.meta.url));

/** Products whose photo is served by this stub, by what the card meets. */
const PHOTO_PRODUCTS = Object.fromEntries(
  [
    ["p-photo", "photo.png"],
    ["p-photo-missing", "missing.png"],
    ["p-photo-garbage", "garbage.webp"],
  ].map(([id, file]) => {
    const image = `http://localhost:${PORT}/img/${file}`;
    return [
      id,
      {
        ...PRODUCT,
        id,
        image,
        offers: PRODUCT.offers.map((offer) => ({ ...offer, images: [image] })),
      },
    ];
  }),
);

/**
 * What `GET /sitemap/products` lists, ordered by id as the API orders them:
 * a Latin title (slugged), an Arabic one (no slug: the bare id), none at all.
 */
const SITEMAP_PRODUCTS = [
  {
    id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    title_en: "SG90 Micro Servo (180°)",
    changed_at: "2026-10-02T08:30:00Z",
  },
  {
    id: "6ec0bd7f-11c0-43da-975e-2a8ad9ebae0b",
    title_en: "مقاومة كربون",
    changed_at: "2026-09-15T00:00:00Z",
  },
  {
    id: "9f8e7d6c-5b4a-4321-8fed-cba987654321",
    title_en: null,
    changed_at: "2026-08-01T00:00:00Z",
  },
];

/** Keyset paging by id, like the API: `after` an id, at most `limit`. */
function sitemapProducts(url) {
  const after = url.searchParams.get("after");
  const limit = Number(url.searchParams.get("limit") ?? 50000);
  const items = SITEMAP_PRODUCTS.filter((p) => !after || p.id > after).slice(0, limit);
  return {
    items,
    next: items.length === limit ? items[items.length - 1].id : null,
    total: after ? null : SITEMAP_PRODUCTS.length,
  };
}

function search(url) {
  const q = url.searchParams.get("q") ?? "";
  const domain = url.searchParams.get("domain");
  const minSuppliers = Number(url.searchParams.get("min_suppliers") ?? 0);

  let hits = [HIT, HIT_2];
  if (q.toLowerCase().includes("nothing")) hits = [];
  if (domain === "tools") hits = [];
  if (minSuppliers > 1) hits = [HIT];
  // Within one shop, a one-shop result is that shop's own.
  const shop = url.searchParams.get("shop");
  if (shop) {
    hits = hits.map((hit) =>
      hit.supplier_count === 1 ? { ...hit, supplier_name: shopName(shop) ?? shop } : hit,
    );
  }
  // The stale shop's products are as old as the shop (80 days), and the one
  // place these generic hits honour a filter: the stale filter (C2b), so its
  // page can show that it lists them anyway, and that the chip hides them.
  if (shop === "stale-shop") {
    const old = Math.floor(Date.now() / 1000) - 80 * 86_400;
    hits = hits.map((hit) => ({ ...hit, last_verified_at: old }));
    if (url.searchParams.get("fresh") === "true") hits = [];
  }

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
      // Counted, so a filter that empties the hits empties this too.
      in_stock: hits.length ? { true: hits.filter((hit) => hit.in_stock).length } : {},
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
  const credited = photoShopRoute(url, PORT);
  if (credited) return send(...credited);
  if (path === "/stats") return send(200, { products: 57207, suppliers: 8, categories: 249 });
  if (path === "/categories") {
    const domain = url.searchParams.get("domain");
    if (domain === FAILING_DEPARTMENT) return send(500, { detail: "database unreachable" });
    const all = [...CATEGORIES, ...DEPARTMENT_CATEGORIES];
    return send(200, domain ? all.filter((c) => c.domain === domain) : all);
  }
  const fixture = path === "/search" && searchFixture(url);
  if (fixture) return send(fixture.status, fixture.body);
  const department = path === "/search" && departmentSearch(url);
  if (department) return send(department.status, department.body);
  if (path === "/search") return send(200, search(url));
  if (path === "/sitemap/products") return send(200, sitemapProducts(url));
  if (path === "/crawler/activity") return send(200, crawlerActivity());
  if (path === "/.well-known/http-message-signatures-directory") {
    // Shaped like the API's: a JWKS, its media type, and the signature headers
    // the proxy must pass through untouched.
    res.writeHead(200, {
      "content-type": "application/http-message-signatures-directory+json",
      "signature-input":
        'sig1=("@authority";req);created=1;expires=301;keyid="k";alg="ed25519";tag="http-message-signatures-directory"',
      signature: "sig1=:c3R1Yg==:",
    });
    return res.end(JSON.stringify({ keys: [{ kty: "OKP", crv: "Ed25519", x: "stub" }] }));
  }
  if (path === "/products/prod-1/similar") {
    // A ProductSummary: no offers key at all, which is the point of the shape.
    const summary = { ...PRODUCT };
    delete summary.offers;
    return send(200, [
      { ...summary, id: "prod-2", title_en: "LM358N Dual Op-Amp", title_ar: null, min_price: 12.5 },
    ]);
  }
  if (path === "/products/prod-1") return send(200, PRODUCT);
  // What the API says to an id that is not a UUID.
  if (path === "/products/malformed-id") return send(422, { detail: "not a valid uuid" });
  if (path === "/listings/listing-1") return send(200, LISTING);
  // The offers are listings too, so opening one has somewhere to land.
  if (path === "/listings/off-1") return send(200, { ...LISTING, id: "off-1" });
  if (path === "/listings/off-2")
    return send(200, {
      ...LISTING,
      id: "off-2",
      price: null,
      supplier: { ...SUPPLIER, id: "sup-2", slug: "shop-b", name: "Shop B" },
    });
  if (path === "/listings/listing-gone") return send(200, WITHDRAWN);
  if (path === "/listings/listing-orphan")
    return send(200, { ...LISTING, id: "listing-orphan", product_id: null });
  // Product photos for the link-preview card: one that loads, one the shop
  // has lost, and one that claims to be an image and is not.
  if (path === "/img/photo.png") {
    res.writeHead(200, { "content-type": "image/png" });
    return res.end(PHOTO_PNG);
  }
  if (path === "/img/garbage.webp") {
    res.writeHead(200, { "content-type": "image/webp" });
    return res.end("not an image");
  }
  const photoProduct = PHOTO_PRODUCTS[path.replace(/^\/products\//, "")];
  if (photoProduct) return send(200, photoProduct);

  const phase2 = phase2Fixture(path);
  if (phase2) return send(...phase2);

  const shop = shopRoute(path);
  if (shop) return send(...shop);

  const product = productFixture(path);
  if (product) return send(...product);

  return send(404, { detail: "not found" });
});

server.listen(PORT, () => {
  process.stdout.write(`stub api on ${PORT}\n`);
});
