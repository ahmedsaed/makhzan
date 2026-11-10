/**
 * Photos credited to their shops: the badge on every product photo.
 *
 *   /products/p-two-shops         three photos, two shops' (A leads, then B)
 *   /products/p-two-shops/similar two summaries, one credited, one from an
 *                                 API that predates `image_shop`
 *   /search?q=photobadge          a credited photo, an uncredited one (the
 *                                 field absent, as in an older response), and
 *                                 one with no photo at all
 *
 * The photos are the stub's own PNG, told apart by a query string. Shops are
 * fictional (the repo is public).
 */

const NOW = Math.floor(Date.now() / 1000);

const shop = (slug, name) => ({
  id: `sup-${slug}`,
  slug,
  name,
  name_ar: null,
  area: null,
  governorate: null,
  website_url: `https://${slug}.test`,
});

const SHOP_A = shop("shop-a", "Shop A");
// Long on purpose: the badge truncates rather than covering the photo.
const SHOP_B = shop("shop-b", "Shop B Electronics and Components Egypt");

const photo = (port, tag) => `http://localhost:${port}/img/photo.png?from=${tag}`;

function product(port) {
  return {
    id: "p-two-shops",
    part_number: "SG90",
    title_en: "SG90 Micro Servo 9g",
    title_ar: null,
    brand: null,
    image: photo(port, "a1"),
    image_shop: { slug: SHOP_A.slug, name: SHOP_A.name },
    supplier_count: 2,
    offer_count: 2,
    min_price: 60,
    max_price: 75,
    currency: "EGP",
    in_stock: true,
    last_verified_at: new Date().toISOString(),
    category: null,
    offers: [
      {
        id: "off-badge-a",
        title_en: "SG90 Servo",
        title_ar: null,
        price: 60,
        currency: "EGP",
        stock_signal: "in_stock",
        source_url: "https://shop-a.test/p/sg90",
        images: [photo(port, "a1"), photo(port, "a2")],
        last_verified_at: new Date().toISOString(),
        supplier: SHOP_A,
      },
      {
        id: "off-badge-b",
        title_en: "Servo SG90 9g",
        title_ar: null,
        price: 75,
        currency: "EGP",
        stock_signal: "in_stock",
        source_url: "https://shop-b.test/p/sg90",
        images: [photo(port, "b1")],
        last_verified_at: new Date().toISOString(),
        supplier: SHOP_B,
      },
    ],
  };
}

function summary(port, id, title, image, imageShop) {
  const { offers: _offers, ...rest } = product(port);
  const out = { ...rest, id, title_en: title, image, supplier_count: 1, offer_count: 1 };
  if (imageShop === undefined) delete out.image_shop;
  else out.image_shop = imageShop;
  return out;
}

function hit(port, id, title, image, imageShop) {
  const out = {
    id,
    domain: "electronics",
    part_number: null,
    title_en: title,
    title_ar: null,
    brand: null,
    category_slug: null,
    category_ref: null,
    category_name: null,
    supplier_name: "Shop A",
    supplier_count: 1,
    offer_count: 1,
    min_price: 60,
    max_price: 60,
    currency: "EGP",
    in_stock: true,
    image,
    last_verified_at: NOW,
  };
  if (imageShop !== undefined) out.image_shop = imageShop;
  return out;
}

/** [status, body] for a route this fixture answers, else null. */
export function photoShopRoute(url, port) {
  const path = url.pathname;
  if (path === "/products/p-two-shops") return [200, product(port)];
  if (path === "/products/p-two-shops/similar") {
    return [
      200,
      [
        summary(port, "p-badge-similar", "MG996R Servo", photo(port, "s1"), {
          slug: SHOP_B.slug,
          name: SHOP_B.name,
        }),
        summary(port, "p-badge-old", "MG90S Servo", photo(port, "s2"), undefined),
      ],
    ];
  }
  if (path === "/search" && url.searchParams.get("q") === "photobadge") {
    const hits = [
      hit(port, "p-badge-1", "Alpha servo, credited", photo(port, "h1"), {
        slug: SHOP_B.slug,
        name: SHOP_B.name,
      }),
      hit(port, "p-badge-2", "Bravo servo, no credit", photo(port, "h2"), undefined),
      hit(port, "p-badge-3", "Servo without a photo", null, null),
    ];
    return [
      200,
      {
        query: "photobadge",
        identifier_query: false,
        total: hits.length,
        limit: 24,
        offset: 0,
        hits,
        facets: { domain: { electronics: 3 }, category_ref: {}, in_stock: { true: 3 } },
      },
    ];
  }
  return null;
}
