/**
 * Stub payloads for the product page (tests/e2e/product.spec.ts): one offer
 * with a stale price, several offers with out-of-stock ones to fold, every
 * offer out of stock, and one whose shop published specs and datasheets.
 * Shops are fictional; check dates are relative to when
 * the stub starts, so the freshness tiers hold whatever day the suite runs.
 */

const DAY = 86_400_000;
const daysAgo = (days) => new Date(Date.now() - days * DAY).toISOString();

const CATEGORY = {
  ref: "electronics:ics",
  domain: "electronics",
  slug: "ics",
  name_en: "Integrated Circuits",
  name_ar: null,
};

const shop = (slug, name) => ({
  id: `sup-${slug}`,
  slug,
  name,
  name_ar: null,
  area: null,
  governorate: null,
  website_url: `https://${slug}.test`,
});

const VOLT = shop("volt-corner", "Volt Corner");
const NILE = shop("nile-parts", "Nile Parts");
const DELTA = shop("delta-bench", "Delta Bench");

/** Where the cached-thumbnail photos live; the spec intercepts this host. */
const MEDIA = "https://media.nile-parts.test";

/** `details`: what the shop published (brand, specs, documents). The API sends
 *  `specs` and `documents` on every offer, empty when there are none. */
function offer(id, supplier, title, price, stock, age, images = [], details = {}) {
  return {
    brand: null,
    specs: {},
    documents: [],
    ...details,
    id,
    title_en: title,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: `https://${supplier.slug}.test/p/${id}?variant=1`,
    images,
    last_verified_at: daysAgo(age),
    supplier,
  };
}

function product(id, title, offers, extra = {}) {
  const inStock = offers.filter((o) => o.stock_signal === "in_stock");
  const prices = offers.map((o) => o.price).filter((p) => p !== null);
  return {
    id,
    part_number: null,
    title_en: title,
    title_ar: null,
    brand: null,
    image: offers[0].images[0] ?? null,
    supplier_count: new Set(offers.map((o) => o.supplier.slug)).size,
    offer_count: offers.length,
    min_price: prices.length ? Math.min(...prices) : null,
    max_price: prices.length ? Math.max(...prices) : null,
    currency: "EGP",
    in_stock: inStock.length > 0,
    last_verified_at: offers[0].last_verified_at,
    category: CATEGORY,
    offers,
    ...extra,
  };
}

const PRODUCTS = {
  "p-single": product(
    "p-single",
    "Digital Caliper 150mm x 0.01mm IP54",
    [
      offer("o-single", VOLT, "Digital Caliper 150mm x 0.01mm IP54", 850, "in_stock", 74, [
        "https://volt-corner.test/img/caliper-1.jpg",
        "https://volt-corner.test/img/caliper-2.jpg",
      ]),
    ],
    { part_number: "DC-150" },
  ),
  "p-multi": product("p-multi", "ESP32 Development Board 30 pin", [
    // Deliberately not in price order: the page sorts.
    // Two shops publish specs; the page opens on the richer one (o-m1, two
    // specs) and keeps the other behind its "From" tab.
    offer("o-m3", NILE, "ESP32 Development Board 30-Pin with CP2102", 280, "in_stock", 20, [], {
      specs: { "USB Chip": "CP2102" },
    }),
    offer(
      "o-m1",
      DELTA,
      "ESP32 Development Board 30 pin (WIFI - Bluetooth)",
      260,
      "in_stock",
      17,
      [],
      { specs: { "Flash Memory": "4 MB", "GPIO Pins": "30" } },
    ),
    offer("o-oos1", VOLT, "ESP32 DevKit 30 pin, old stock", 240, "out_of_stock", 9),
    offer("o-m5", NILE, "ESP32 Development Board 38-Pin – Micro USB", 295, "in_stock", 28),
    offer("o-m2", NILE, "ESP32 Development Board 30-Pin with CP2102 Type-C", 270, "in_stock", 29),
    offer("o-oos2", DELTA, "ESP32 38 pin board", 300, "out_of_stock", 60),
    offer("o-m4", DELTA, "ESP32S ESP-WROOM-32 38-Pin CP2102", 290, "in_stock", 16),
  ]),
  // What the shop published (rule C4): brand, spec rows and datasheets, and
  // photos that are cached 150px thumbnails with a full-size original beside
  // them (tests/e2e/product.spec.ts serves those through page.route).
  "p-specs": product("p-specs", "UT61E Digital Multimeter True RMS", [
    offer(
      "o-spec",
      NILE,
      "UT61E Digital Multimeter True RMS",
      2450,
      "in_stock",
      3,
      [
        `${MEDIA}/uploads/cache/2025-01-10/product/image/ut61e-front-q-80-h-150.webp`,
        `${MEDIA}/uploads/cache/2025-01-10/product/image/ut61e-back-q-80-h-150.webp`,
      ],
      {
        brand: "UNI-T",
        specs: { Model: "UT61E", "DC Voltage": "220mV – 1000V", Display: "22000 counts" },
        documents: [
          { url: "https://nile-parts.test/files/ut61e-manual.pdf", label: "UT61E user manual" },
          { url: "https://nile-parts.test/files/ut61e-datasheet.pdf", label: null },
        ],
      },
    ),
  ]),
  "p-oos": product("p-oos", "LM2596 Buck Converter Module", [
    offer("o-x1", VOLT, "LM2596 DC-DC Buck Module", 45, "out_of_stock", 30),
    offer("o-x2", NILE, "LM2596 Step Down Converter", 40, "out_of_stock", 2),
    offer("o-x3", DELTA, "LM2596 Adjustable Buck", 50, "out_of_stock", 12),
  ]),
};

const DESCRIPTION =
  "Range 0–150mm, reading 0.01mm, IP54 housing against dust and splashes. " +
  "Metric and inch conversion at any position, zero setting anywhere along the beam. " +
  "Runs on one CR2032 cell, with automatic power-off after five minutes idle. " +
  "Packed in a hard plastic case with a spare battery. Hardened stainless steel jaws " +
  "for outside, inside, depth and step measurements. This sentence is the end of it.";

const DESCRIPTIONS = {
  "o-single": DESCRIPTION,
  "o-spec": "True RMS multimeter with a 22000-count display and a USB data link.",
};

const SUPPLIERS = {
  "volt-corner": VOLT,
  "nile-parts": NILE,
  "delta-bench": DELTA,
};

/** `[status, body]` for a path this fixture owns, or null. */
export function productFixture(path) {
  const similar = path.match(/^\/products\/([^/]+)\/similar$/);
  if (similar && PRODUCTS[similar[1]]) {
    const summary = { ...PRODUCTS["p-oos"], id: "p-oos" };
    delete summary.offers;
    return [200, [summary, { ...summary, id: "p-similar-2", title_en: "Mini Buck Module" }]];
  }
  const productId = path.match(/^\/products\/([^/]+)$/)?.[1];
  if (productId && PRODUCTS[productId]) return [200, PRODUCTS[productId]];

  const listingId = path.match(/^\/listings\/([^/]+)$/)?.[1];
  for (const item of Object.values(PRODUCTS)) {
    const found = item.offers.find((o) => o.id === listingId);
    if (found) {
      return [
        200,
        {
          ...found,
          product_id: item.id,
          description_en: DESCRIPTIONS[found.id] ?? null,
          description_ar: null,
          part_number: item.part_number,
          unit: null,
          status: "active",
          category: CATEGORY,
        },
      ];
    }
  }

  const slug = path.match(/^\/suppliers\/([^/]+)$/)?.[1];
  if (slug && SUPPLIERS[slug]) return [200, { ...SUPPLIERS[slug], listing_count: 4340 }];
  return null;
}
