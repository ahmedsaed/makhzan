/**
 * Shop payloads for the stub API: `/suppliers`, one shop's profile and its
 * listings, shaped like apps/api/app/routers/suppliers.py.
 *
 * Three fictional shops cover what the pages must tell apart: one checked
 * days ago, one the crawler lost months ago (stale, rule F3), and one with no
 * active listings left, which the list hides. Check times are relative to
 * the request, so the tiers hold whatever day the suite runs.
 */

const DAY = 86_400_000;
const ago = (days) => new Date(Date.now() - days * DAY).toISOString();

const CATEGORY = {
  ref: "electronics:ics",
  domain: "electronics",
  slug: "ics",
  name_en: "Integrated Circuits",
  name_ar: null,
};

function profile(summary, extra) {
  return {
    area: null,
    governorate: null,
    contact: null,
    top_categories: [],
    ...summary,
    ...extra,
  };
}

/**
 * Shop A: every detail. Its numbers, email and branch listed by a person from
 * its contact page; its address from its Google Maps listing, which it has not
 * claimed; its WhatsApp and hours read by the crawler.
 */
const SHOP_A_CONTACT = {
  phones: ["+20223456789", "+20223456780"],
  whatsapp: "+201001234567",
  email: "sales@shop-a.test",
  address: "12 Example Street, 2nd floor",
  area: "Bab El Louk",
  governorate: "Cairo",
  maps_url: "https://maps.app.goo.gl/shopA",
  // As schema.org markup has it; the page reads it in plain English.
  opening_hours: ["Sa,Su,Mo,Tu,We,Th 10:00-22:00"],
  branches: [
    {
      name: "Giza branch",
      address: "3 Other Street",
      area: "Dokki",
      governorate: "Giza",
      phones: ["+20233334444"],
      maps_url: "https://maps.app.goo.gl/shopAGiza",
    },
  ],
  sources: [
    {
      origin: "listed",
      url: "https://www.shop-a.test/contact-us",
      checked_on: "2026-11-03",
      fields: ["phones", "email", "branches"],
    },
    {
      origin: "listed",
      url: "https://www.google.com/maps/place/Shop+A",
      checked_on: "2026-11-03",
      fields: ["address", "area", "governorate", "maps_url"],
    },
    {
      origin: "read",
      url: "https://www.shop-a.test/",
      checked_on: "2026-11-08",
      fields: ["whatsapp", "opening_hours"],
    },
  ],
};

/** Stale Shop: only an address, which the crawler read; no phone, no hours. */
const STALE_SHOP_CONTACT = {
  phones: [],
  whatsapp: null,
  email: null,
  address: "31 شارع المثال",
  area: null,
  governorate: null,
  maps_url: null,
  opening_hours: [],
  branches: [],
  sources: [
    {
      origin: "read",
      url: "https://stale-shop.test/",
      checked_on: "2026-08-20",
      fields: ["address"],
    },
  ],
};

function summaries() {
  return [
    {
      slug: "shop-a",
      name: "Shop A",
      name_ar: null,
      website_url: "https://www.shop-a.test/",
      listing_count: 120,
      in_stock_count: 84,
      last_verified_at: ago(3),
      domains: [
        { domain: "electronics", count: 100 },
        { domain: "tools", count: 15 },
        { domain: "chemicals", count: 5 },
      ],
    },
    {
      slug: "stale-shop",
      name: "Stale Shop",
      name_ar: null,
      website_url: "https://stale-shop.test",
      listing_count: 40,
      in_stock_count: 30,
      last_verified_at: ago(80),
      domains: [{ domain: "electronics", count: 40 }],
    },
    {
      slug: "gone-shop",
      name: "Gone Shop",
      name_ar: null,
      website_url: "https://gone-shop.test",
      listing_count: 0,
      in_stock_count: 0,
      last_verified_at: null,
      domains: [],
    },
  ];
}

function listing(id, productId, supplier) {
  return {
    id,
    product_id: productId,
    title_en: `Op-amp ${id}`,
    title_ar: null,
    description_en: null,
    description_ar: null,
    part_number: null,
    brand: null,
    price: 12.5,
    currency: "EGP",
    unit: null,
    stock_signal: "in_stock",
    status: "active",
    images: [],
    source_url: `${supplier.website_url}p/${id}`,
    last_verified_at: supplier.last_verified_at ?? ago(3),
    supplier: { id: `sup-${supplier.slug}`, ...supplier, area: null, governorate: null },
    category: CATEGORY,
  };
}

/** A fixture shop's display name, for search hits scoped to it. */
export function shopName(slug) {
  return summaries().find((s) => s.slug === slug)?.name ?? null;
}

/** `[status, body]` for a shop route, or null when the path is not one. */
export function shopRoute(path) {
  const shops = summaries();
  if (path === "/suppliers") return [200, shops];

  const match = path.match(/^\/suppliers\/([^/]+)(\/listings)?$/);
  const shop = match && shops.find((s) => s.slug === match[1]);
  if (!match) return null;
  // Not one of ours: let the other fixtures answer; the stub 404s if none does.
  if (!shop) return null;

  if (match[2]) {
    const { slug, name, name_ar, website_url } = shop;
    const owner = { slug, name, name_ar, website_url, last_verified_at: shop.last_verified_at };
    // The second has no product, so the page must leave it out (P1).
    const items = shop.listing_count
      ? [listing(`${slug}-1`, "prod-1", owner), listing(`${slug}-2`, null, owner)]
      : [];
    return [200, { total: items.length, limit: 24, offset: 0, items }];
  }

  return [
    200,
    profile(
      shop,
      shop.slug === "shop-a"
        ? {
            area: "Bab El Louk",
            governorate: "Cairo",
            contact: SHOP_A_CONTACT,
            top_categories: [
              { ...CATEGORY, count: 60 },
              { ref: "tools:measurement", name_en: "Measuring Tools", name_ar: null, count: 12 },
            ],
          }
        : shop.slug === "stale-shop"
          ? { contact: STALE_SHOP_CONTACT }
          : {},
    ),
  ];
}
