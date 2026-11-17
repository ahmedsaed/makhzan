/**
 * The shop view and "Matched by AI" (tests/e2e/shop-view.spec.ts).
 *
 *   /products/p-ai   five offers from five shops, lowest price first:
 *     Nile Parts       EGP 385, in stock, the rules' match, two photos, a description
 *     Volt Corner      EGP 410, in stock, matched by AI, one photo, a description and specs
 *     Delta Bench      EGP 425, in stock, the rules' match, no photo, wrote nothing (no tab)
 *     Oasis Parts Lab  EGP 450, in stock, matched by AI, one photo, a description
 *     Sinai Spares     EGP 300, out of stock (folded), the rules' match, one photo
 *
 * The photos are SVGs the stub draws (`/img/sv/<tag>.svg`), each naming its
 * shop, so a screenshot shows whose photo leads. Shops are fictional (the
 * repo is public); check dates are relative to when the stub starts.
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
  contact: null,
});

const NILE = shop("nile-parts", "Nile Parts");
const VOLT = shop("volt-corner", "Volt Corner");
const DELTA = shop("delta-bench", "Delta Bench");
const OASIS = shop("oasis-parts-lab", "Oasis Parts Lab");
const SINAI = shop("sinai-spares", "Sinai Spares");

function offer(port, id, supplier, title, price, stock, age, photos, extra = {}) {
  return {
    brand: null,
    specs: {},
    documents: [],
    matched_by: "rules",
    ...extra,
    id,
    title_en: title,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: `https://${supplier.slug}.test/p/${id}`,
    images: photos.map((tag) => `http://localhost:${port}/img/sv/${tag}.svg`),
    last_verified_at: daysAgo(age),
    supplier,
  };
}

function product(port) {
  const offers = [
    offer(
      port,
      "o-ai-oasis",
      OASIS,
      "Stepper Driver TB6600 Upgraded (TB67S109 chip) 4A",
      450,
      "in_stock",
      3,
      ["oasis-1"],
      { matched_by: "ai" },
    ),
    offer(
      port,
      "o-ai-nile",
      NILE,
      "TB6600 Stepper Motor Driver 4A 9-42V 32 Microstep",
      385,
      "in_stock",
      2,
      ["nile-1", "nile-2"],
    ),
    offer(
      port,
      "o-ai-delta",
      DELTA,
      "TB6600 Stepper Motor Driver Controller 4.0A 42VDC",
      425,
      "in_stock",
      5,
      [],
    ),
    offer(
      port,
      "o-ai-volt",
      VOLT,
      "TB6600 4A Stepper Driver Module for NEMA 17 / NEMA 23",
      410,
      "in_stock",
      4,
      ["volt-1"],
      {
        matched_by: "ai",
        specs: { "Input Voltage": "9–42 V DC", "Output Current": "0.5–4.0 A" },
      },
    ),
    offer(port, "o-ai-sinai", SINAI, "TB6600 Driver Board, old stock", 300, "out_of_stock", 6, [
      "sinai-1",
    ]),
  ];
  return {
    id: "p-ai",
    part_number: "TB6600",
    title_en: "TB6600 Stepper Motor Driver 4A 9–42V",
    title_ar: null,
    brand: null,
    image: offers[1].images[0],
    image_shop: { slug: NILE.slug, name: NILE.name },
    supplier_count: 5,
    offer_count: 5,
    min_price: 385,
    max_price: 450,
    currency: "EGP",
    in_stock: true,
    last_verified_at: daysAgo(2),
    category: CATEGORY,
    offers,
    ai_matched_count: 2,
    // The regroup's representative (in stock, English title, photo, cheapest):
    // Nile, the cheapest in stock too.
    representative_offer_id: "o-ai-nile",
  };
}

/**
 * /products/p-rep: the representative is not the cheapest. Delta Bench is the
 * cheapest in stock but has no photo, so the regroup took Volt Corner's
 * listing (in stock, English title, photo), and the product's title is Volt's.
 *
 *     Sinai Spares     EGP 300, out of stock, one photo
 *     Delta Bench      EGP 380, in stock, no photo
 *     Volt Corner      EGP 410, in stock, one photo: the representative
 */
function repProduct(port) {
  const offers = [
    offer(port, "o-rep-sinai", SINAI, "TB6600 Driver Board, old stock", 300, "out_of_stock", 6, [
      "sinai-1",
    ]),
    offer(
      port,
      "o-rep-delta",
      DELTA,
      "TB6600 Stepper Motor Driver Controller",
      380,
      "in_stock",
      2,
      [],
    ),
    offer(
      port,
      "o-rep-volt",
      VOLT,
      "TB6600 4A Stepper Driver Module for NEMA 17 / NEMA 23",
      410,
      "in_stock",
      3,
      ["volt-1"],
    ),
  ];
  return {
    id: "p-rep",
    part_number: "TB6600",
    title_en: "TB6600 4A Stepper Driver Module for NEMA 17 / NEMA 23",
    title_ar: null,
    brand: null,
    image: offers[2].images[0],
    image_shop: { slug: VOLT.slug, name: VOLT.name },
    supplier_count: 3,
    offer_count: 3,
    min_price: 380,
    max_price: 410,
    currency: "EGP",
    in_stock: true,
    last_verified_at: daysAgo(2),
    category: CATEGORY,
    offers,
    ai_matched_count: 0,
    representative_offer_id: "o-rep-volt",
  };
}

const DESCRIPTIONS = {
  "o-ai-nile":
    "TB6600 stepper driver for NEMA 17 and NEMA 23 motors. Eight current settings from 0.5 A to 4 A, and up to 32 microsteps, set on the DIP switches.",
  "o-ai-volt":
    "Driver module for two-phase stepper motors, with optical isolation on every input. Ships with a printed DIP switch table.",
  "o-ai-oasis":
    "Upgraded TB6600 stepper driver built on the TB67S109 chip, which runs cooler than the original at the same current. Same wiring and DIP switch table as the classic TB6600.",
};

/** `[status, body]` for a path this fixture owns, or null. */
export function shopViewFixture(path, port) {
  if (path === "/products/p-ai/similar") return [200, []];
  if (path === "/products/p-ai") return [200, product(port)];
  if (path === "/products/p-rep/similar") return [200, []];
  if (path === "/products/p-rep") return [200, repProduct(port)];
  const listingId = path.match(/^\/listings\/(o-ai-[a-z]+)$/)?.[1];
  const found = listingId && product(port).offers.find((o) => o.id === listingId);
  if (found) {
    return [
      200,
      {
        ...found,
        product_id: "p-ai",
        description_en: DESCRIPTIONS[found.id] ?? null,
        description_ar: null,
        part_number: "TB6600",
        unit: null,
        status: "active",
        category: CATEGORY,
      },
    ];
  }
  return null;
}

/** A placeholder photo naming its shop: `/img/sv/nile-2.svg`. */
export function shopViewPhoto(path) {
  const tag = path.match(/^\/img\/sv\/([a-z]+)-(\d)\.svg$/);
  if (!tag) return null;
  const [, shopTag, n] = tag;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">` +
    `<rect width="400" height="400" fill="#ffffff"/>` +
    `<rect x="80" y="70" width="240" height="180" rx="10" fill="#2f3440"/>` +
    `<rect x="110" y="125" width="180" height="70" rx="4" fill="#e9e6dc"/>` +
    `<text x="200" y="168" text-anchor="middle" font-family="sans-serif" font-weight="700" font-size="26" fill="#2f3440">TB6600</text>` +
    `<text x="200" y="300" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#4a4f5a">${shopTag} · photo ${n}</text>` +
    `</svg>`
  );
}
