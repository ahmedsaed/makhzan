import { describe, expect, it } from "vitest";

import type { Category, Offer, Product, StockSignal } from "@/lib/api";
import {
  categoryTrail,
  galleryImages,
  galleryPhotos,
  jsonLdText,
  JSON_LD_SPECS,
  offerDetails,
  orderOffers,
  photoNumbered,
  primaryOffer,
  productJsonLd,
  shopsFact,
  splitOffers,
  summarizeOffers,
  summaryText,
} from "@/lib/product";

const NOW = Date.parse("2026-11-06T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW - days * 86_400_000).toISOString();

function offer(
  id: string,
  price: number | null,
  stock: StockSignal = "in_stock",
  { shop = "shop-a", age = 1, images = [] as string[], url = true } = {},
): Offer {
  return {
    id,
    title_en: `Offer ${id}`,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: url ? `https://${shop}.test/${id}` : null,
    images,
    last_verified_at: daysAgo(age),
    supplier: {
      id: shop,
      slug: shop,
      name: shop.toUpperCase(),
      name_ar: null,
      area: null,
      governorate: null,
      website_url: null,
    },
  };
}

function product(offers: Offer[], extra: Partial<Product> = {}): Product {
  return {
    id: "p1",
    part_number: null,
    title_en: "Thing",
    title_ar: null,
    brand: null,
    image: null,
    supplier_count: 1,
    offer_count: offers.length,
    min_price: null,
    max_price: null,
    currency: "EGP",
    in_stock: true,
    last_verified_at: null,
    category: null,
    offers,
    ...extra,
  };
}

const ids = (offers: Offer[]) => offers.map((o) => o.id);

describe("offer order", () => {
  it("is lowest price first, with no price last rather than free", () => {
    const ordered = orderOffers([
      offer("c", 30),
      offer("none", null),
      offer("a", 10),
      offer("b", 20),
    ]);
    expect(ids(ordered)).toEqual(["a", "b", "c", "none"]);
  });

  it("breaks a price tie by the more recently checked", () => {
    const ordered = orderOffers([offer("old", 10, "in_stock", { age: 30 }), offer("new", 10)]);
    expect(ids(ordered)).toEqual(["new", "old"]);
  });

  it("folds out-of-stock offers, ordered, under the list", () => {
    const { listed, outOfStock } = splitOffers([
      offer("gone-2", 5, "out_of_stock"),
      offer("b", 20),
      offer("gone-1", 1, "out_of_stock"),
      offer("unknown", 15, "unknown"),
    ]);
    expect(ids(listed)).toEqual(["unknown", "b"]);
    expect(ids(outOfStock)).toEqual(["gone-1", "gone-2"]);
  });

  it("folds nothing when every offer is out of stock", () => {
    const { listed, outOfStock } = splitOffers([
      offer("b", 20, "out_of_stock"),
      offer("a", 10, "out_of_stock"),
    ]);
    expect(ids(listed)).toEqual(["a", "b"]);
    expect(outOfStock).toEqual([]);
  });
});

describe("in-stock summary", () => {
  it("counts in-stock offers and shops, and ranges their prices only", () => {
    const summary = summarizeOffers([
      offer("a", 260, "in_stock", { shop: "x" }),
      offer("b", 295, "low_stock", { shop: "y" }),
      offer("c", 280, "in_stock", { shop: "y" }),
      offer("d", 100, "out_of_stock", { shop: "z" }),
    ]);
    expect(summary).toMatchObject({
      state: "in_stock",
      offerCount: 3,
      shopCount: 2,
      min: 260,
      max: 295,
    });
    expect(summaryText(summary)).toBe("3 offers in stock at 2 shops");
  });

  it("says so plainly when every shop is out of stock", () => {
    const summary = summarizeOffers([
      offer("a", 40, "out_of_stock", { shop: "x" }),
      offer("b", 50, "out_of_stock", { shop: "y" }),
    ]);
    expect(summary.state).toBe("out_of_stock");
    expect(summaryText(summary)).toBe("Out of stock at all 2 shops");
  });

  it("does not call unknown stock in stock", () => {
    const summary = summarizeOffers([offer("a", 10, "unknown"), offer("b", 5, "out_of_stock")]);
    expect(summary.state).toBe("unconfirmed");
    expect(summaryText(summary)).toBe("1 offer at 1 shop, stock not confirmed");
  });
});

describe("primary offer", () => {
  it("is the cheapest in stock, not the cheapest overall", () => {
    const primary = primaryOffer([
      offer("gone", 1, "out_of_stock"),
      offer("dear", 50),
      offer("cheap", 20),
    ]);
    expect(primary?.id).toBe("cheap");
  });

  it("skips an offer with nowhere to link to", () => {
    expect(primaryOffer([offer("nolink", 1, "in_stock", { url: false }), offer("b", 9)])?.id).toBe(
      "b",
    );
  });

  it("is the most recently checked when every shop is out of stock", () => {
    const primary = primaryOffer([
      offer("cheap-old", 10, "out_of_stock", { age: 40 }),
      offer("recent", 30, "out_of_stock", { age: 2 }),
      offer("mid", 20, "out_of_stock", { age: 12 }),
    ]);
    expect(primary?.id).toBe("recent");
  });

  it("is null when no offer links anywhere", () => {
    expect(primaryOffer([offer("a", 1, "in_stock", { url: false })])).toBeNull();
  });
});

describe("gallery", () => {
  it("leads with the product photo and lists each photo once", () => {
    const images = galleryImages(
      product([offer("a", 1, "in_stock", { images: ["one.jpg", "two.jpg"] })], {
        image: "one.jpg",
      }),
    );
    expect(images).toEqual(["one.jpg", "two.jpg"]);
  });

  it("credits each photo to the shop whose offer it came from", () => {
    const photos = galleryPhotos(
      product(
        [
          offer("a", 1, "in_stock", { shop: "shop-a", images: ["a1.jpg", "a2.jpg"] }),
          offer("b", 2, "in_stock", { shop: "shop-b", images: ["b1.jpg"] }),
        ],
        // The product's photo is shop B's, and leads the gallery.
        { image: "b1.jpg" },
      ),
    );
    expect(photos).toEqual([
      { src: "b1.jpg", shop: "SHOP-B" },
      { src: "a1.jpg", shop: "SHOP-A" },
      { src: "a2.jpg", shop: "SHOP-A" },
    ]);
  });

  it("falls back to image_shop for a photo no offer lists, and to nothing without it", () => {
    const shop = { slug: "shop-c", name: "Shop C" };
    expect(galleryPhotos(product([], { image: "c.jpg", image_shop: shop }))).toEqual([
      { src: "c.jpg", shop: "Shop C" },
    ]);
    // An API older than image_shop: the photo still shows, uncredited.
    expect(galleryPhotos(product([], { image: "c.jpg" }))).toEqual([{ src: "c.jpg", shop: null }]);
  });

  it("numbers every photo after the first in its alt text", () => {
    expect(photoNumbered("Servo", 0)).toBe("Servo");
    expect(photoNumbered("Servo", 1)).toBe("Servo, photo 2");
  });
});

describe("breadcrumb trail", () => {
  const category = (ref: string, name: string, parent: string | null): Category => ({
    ref,
    domain: "electronics",
    slug: ref.split(":")[1],
    name_en: name,
    name_ar: null,
    parent,
    count: 1,
  });

  it("walks department › group › category, every crumb a link", () => {
    const leaf = category("electronics:ics", "ICs", "electronics:components");
    const trail = categoryTrail(leaf, [
      category("electronics:components", "Components", null),
      leaf,
    ]);
    expect(trail).toEqual([
      { label: "Electronics", href: "/departments/electronics" },
      { label: "Components", href: "/departments/electronics/components" },
      { label: "ICs", href: "/departments/electronics/ics" },
    ]);
  });

  it("survives a category missing from the taxonomy, and a parent loop", () => {
    const leaf = category("electronics:ics", "ICs", "electronics:ics");
    expect(categoryTrail(leaf, [leaf])).toHaveLength(2);
    expect(categoryTrail(leaf, [])).toHaveLength(2);
  });
});

describe("structured data", () => {
  const URL = "https://makhzan.test/products/p1";
  const now = new Date(NOW);
  type Options = Parameters<typeof productJsonLd>[3];
  const maybe = (p: Product, title = "Thing", options: Options = {}) =>
    productJsonLd(p, URL, title, { now, ...options });
  /** The Product node, for a product that has one. */
  const ld = (p: Product, title = "Thing", options: Options = {}) => {
    const data = maybe(p, title, options);
    if (!data) throw new Error("no Product node");
    return data;
  };

  // makhzan compares other shops' offers; it sells nothing. An Offer would make
  // Google read the page as a merchant listing and ask for shipping, returns
  // and a GTIN (Search Console did, November 2026).
  it("is an AggregateOffer even for one shop, never an Offer", () => {
    const data = ld(product([offer("a", 850)]), "Caliper", { description: "A caliper." });
    expect(data).toMatchObject({
      "@context": "https://schema.org",
      "@type": "Product",
      name: "Caliper",
      url: URL,
      description: "A caliper.",
      offers: {
        "@type": "AggregateOffer",
        priceCurrency: "EGP",
        lowPrice: 850,
        highPrice: 850,
        offerCount: 1,
        availability: "https://schema.org/InStock",
        url: URL,
      },
    });
    expect(JSON.stringify(data)).not.toMatch(/"@type":"Offer"|seller|shippingDetails/);
  });

  // The markup repeats the page's summary (compareOffers), not every price
  // the API returned: Google penalises markup that disagrees with the page.
  it("states the summary's range and count: the in-stock offers, on request left out", () => {
    const p = product([
      offer("a", 300, "out_of_stock", { shop: "shop-a" }),
      offer("b", 260, "in_stock", { shop: "shop-b" }),
      offer("c", 280, "low_stock", { shop: "shop-c" }),
      { ...offer("d", null, "in_stock", { shop: "shop-d" }), price_on_request: true },
    ]);
    const data = ld(p, "Board");
    const summary = summarizeOffers(p.offers, now);
    expect(data.offers).toMatchObject({
      lowPrice: summary.min,
      highPrice: summary.max,
      offerCount: summary.offerCount,
    });
    expect(data.offers).toMatchObject({ lowPrice: 260, highPrice: 280, offerCount: 2 });
    expect(data.offers).not.toHaveProperty("offers");
  });

  it("leaves out offers the page folds as out of date", () => {
    const data = ld(
      product([
        offer("fresh", 500, "in_stock", { shop: "shop-a", age: 2 }),
        offer("old", 90, "in_stock", { shop: "shop-b", age: 120 }),
      ]),
    );
    expect(data.offers).toMatchObject({ lowPrice: 500, highPrice: 500, offerCount: 1 });
  });

  it("is out of stock when every shop is, over the same range the page shows", () => {
    const data = ld(
      product([
        offer("a", 300, "out_of_stock", { shop: "shop-a" }),
        offer("b", 320, "out_of_stock", { shop: "shop-b" }),
      ]),
    );
    expect(data.offers).toMatchObject({
      lowPrice: 300,
      highPrice: 320,
      offerCount: 2,
      availability: "https://schema.org/OutOfStock",
    });
  });

  it("is limited when every shop with stock says low, and claims nothing when unconfirmed", () => {
    const low = ld(product([offer("a", 300, "low_stock")]));
    expect(low.offers).toMatchObject({ availability: "https://schema.org/LimitedAvailability" });
    const unknown = ld(product([offer("a", 300, "unknown")]));
    expect(unknown.offers).not.toHaveProperty("availability");
    const made = ld(product([offer("a", 300, "made_to_order")]));
    expect(made.offers).toMatchObject({ availability: "https://schema.org/MadeToOrder" });
  });

  it("uses one shop's box: its options widen the range", () => {
    const single = {
      ...offer("a", 1700),
      variants: [
        { title: "Red", price: 1700, in_stock: true },
        { title: "Blue", price: 1750, in_stock: true },
        { title: "Gold", price: 2400, in_stock: false },
      ],
    } as Offer;
    expect(ld(product([single])).offers).toMatchObject({ lowPrice: 1700, highPrice: 1750 });
  });

  describe("minimum order", () => {
    const min = (o: Offer, quantity: number): Offer => ({ ...o, min_quantity: quantity });

    it("is the eligible quantity when the one shop has a minimum, at its price of one", () => {
      const data = ld(product([min(offer("a", 0.15), 10)]));
      expect(data.offers).toMatchObject({
        lowPrice: 0.15,
        highPrice: 0.15,
        eligibleQuantity: { "@type": "QuantitativeValue", minValue: 10, unitCode: "C62" },
      });
    });

    it("is the fewest when every offer in the range has one", () => {
      const data = ld(
        product([
          min(offer("a", 0.15, "in_stock", { shop: "shop-a" }), 10),
          min(offer("b", 0.2, "in_stock", { shop: "shop-b" }), 5),
        ]),
      );
      expect(data.offers).toMatchObject({ lowPrice: 0.15, highPrice: 0.2 });
      expect(data.offers?.eligibleQuantity).toMatchObject({ minValue: 5 });
    });

    // Mixed: the lowest needs 10, another sells one. A minimum on the
    // aggregate would say nobody sells singly, which the page contradicts.
    it("claims no minimum when another offer in the range sells singly", () => {
      const data = ld(
        product([
          min(offer("a", 0.15, "in_stock", { shop: "shop-a" }), 10),
          offer("b", 0.5, "in_stock", { shop: "shop-b" }),
        ]),
      );
      expect(data.offers).toMatchObject({ lowPrice: 0.15, highPrice: 0.5, offerCount: 2 });
      expect(data.offers).not.toHaveProperty("eligibleQuantity");
    });
  });

  // A Product with no offers, review or rating is an invalid item for Google;
  // and an Offer without a price, or at zero, would be false.
  it("emits no Product when every price is on request, or there is none", () => {
    const onRequest = { ...offer("a", null), price_on_request: true };
    expect(maybe(product([onRequest]))).toBeNull();
    expect(maybe(product([offer("a", null)]))).toBeNull();
  });

  it("emits no Product for a withdrawn product", () => {
    expect(maybe(product([], { status: "delisted", min_price: 120, max_price: 150 }))).toBeNull();
    expect(maybe(product([offer("a", 120)], { status: "delisted" }))).toBeNull();
  });

  // The page warns that every price is out of date; markup cannot.
  it("emits no Product when every offer is out of date", () => {
    expect(maybe(product([offer("a", 120, "in_stock", { age: 60 })]))).toBeNull();
  });

  it("names the brand the page shows, and never a GTIN", () => {
    const data = ld(product([offer("a", 50)], { brand: "Tower Pro" }));
    expect(data).toMatchObject({ brand: { "@type": "Brand", name: "Tower Pro" } });
    expect(JSON.stringify(data)).not.toMatch(/gtin/);
    expect(ld(product([offer("a", 50)]))).not.toHaveProperty("brand");
  });

  // makhzan's part number is read from titles, often a family prefix
  // ("ESP32"): only a shop stating a number makes it a manufacturer's.
  describe("mpn", () => {
    const stating = (o: Offer, value: string): Offer => ({ ...o, mfr_part_number: value });
    const a = (price = 50) => offer("a", price, "in_stock", { shop: "shop-a" });
    const b = (price = 60) => offer("b", price, "in_stock", { shop: "shop-b" });

    it("is never makhzan's extracted number alone", () => {
      expect(ld(product([a()], { part_number: "ESP32" }))).not.toHaveProperty("mpn");
    });

    it("is makhzan's number when a shop states it too", () => {
      const data = ld(product([stating(a(), "sg 90"), b()], { part_number: "SG90" }));
      expect(data.mpn).toBe("SG90");
    });

    it("is the number one shop states when it differs from makhzan's", () => {
      const data = ld(product([stating(a(), "FRC0603F6803TS")], { part_number: "680K" }));
      expect(data.mpn).toBe("FRC0603F6803TS");
    });

    it("is none when shops state different numbers", () => {
      const data = ld(
        product([stating(a(), "A4988"), stating(b(), "DRV8825")], { part_number: "A4988" }),
      );
      expect(data).not.toHaveProperty("mpn");
    });
  });

  it("marks up the opening shop's specs as PropertyValues, capped", () => {
    const specs = Object.fromEntries(
      Array.from({ length: 30 }, (_, i) => [`Spec ${i}`, `value  ${i}`]),
    );
    const details = offerDetails({ ...offer("a", 50), specs });
    const data = ld(product([offer("a", 50)]), "Thing", { details });
    expect(data.additionalProperty).toHaveLength(JSON_LD_SPECS);
    expect(data.additionalProperty?.[0]).toEqual({
      "@type": "PropertyValue",
      name: "Spec 0",
      value: "value 0",
    });
    expect(ld(product([offer("a", 50)]), "Thing", { details: null })).not.toHaveProperty(
      "additionalProperty",
    );
  });

  // "Fits" is one shop's claim about its own listing: never merged (C4).
  it("names what it fits only when one offer alone states it", () => {
    const fits = (o: Offer, models: string[]): Offer => ({ ...o, compatible_with: models });
    const one = ld(product([fits(offer("a", 50), ["Ender 3", "Ender 3 Pro"]), offer("b", 60)]));
    expect(one.isAccessoryOrSparePartFor).toEqual([
      { "@type": "Product", name: "Ender 3" },
      { "@type": "Product", name: "Ender 3 Pro" },
    ]);
    const two = ld(
      product([
        fits(offer("a", 50, "in_stock", { shop: "shop-a" }), ["Ender 3"]),
        fits(offer("b", 60, "in_stock", { shop: "shop-b" }), ["K1"]),
      ]),
    );
    expect(two).not.toHaveProperty("isAccessoryOrSparePartFor");
    expect(ld(product([offer("a", 50)]))).not.toHaveProperty("isAccessoryOrSparePartFor");
  });

  it("clamps a long description at a word, and leaves out an empty one", () => {
    const long = ld(product([offer("a", 1)]), "x", { description: "word ".repeat(200) });
    expect((long.description as string).length).toBeLessThanOrEqual(500);
    expect(long.description).toMatch(/word…$/);
    expect(ld(product([offer("a", 1)]), "x", { description: "  " })).not.toHaveProperty(
      "description",
    );
  });

  it("cannot close its own script tag", () => {
    expect(jsonLdText({ name: "</script><script>alert(1)" })).not.toContain("</script>");
  });
});

describe("makhzan's facts", () => {
  it("counts shops, listings and the shops with stock", () => {
    expect(
      shopsFact([
        offer("a", 10, "in_stock", { shop: "one" }),
        offer("b", 12, "in_stock", { shop: "one" }),
        offer("c", 11, "out_of_stock", { shop: "two" }),
        offer("d", 9, "low_stock", { shop: "three" }),
      ]),
    ).toEqual({ shops: 3, listings: 4, inStockAt: 2 });
  });
});

describe("stale offers (C2b)", () => {
  const now = new Date(NOW);
  const old = { age: 76 };

  it("folds stale offers apart, whatever their stock, when any offer is fresh", () => {
    const { listed, outOfStock, stale } = splitOffers(
      [
        offer("old-cheap", 1, "in_stock", old),
        offer("b", 20),
        offer("gone", 5, "out_of_stock"),
        offer("old-gone", 2, "out_of_stock", old),
      ],
      now,
    );
    expect(ids(listed)).toEqual(["b"]);
    expect(ids(outOfStock)).toEqual(["gone"]);
    expect(ids(stale)).toEqual(["old-cheap", "old-gone"]);
  });

  it("folds nothing for age when every offer is stale: the page still lists them", () => {
    const { listed, outOfStock, stale } = splitOffers(
      [offer("a", 10, "in_stock", old), offer("b", 5, "out_of_stock", old)],
      now,
    );
    expect(ids(listed)).toEqual(["a"]);
    expect(ids(outOfStock)).toEqual(["b"]);
    expect(stale).toEqual([]);
  });

  it("draws the line after 45 whole days, like the warning", () => {
    const { stale } = splitOffers(
      [offer("a", 10, "in_stock", { age: 45 }), offer("b", 5, "in_stock", { age: 46 })],
      now,
    );
    expect(ids(stale)).toEqual(["b"]);
  });

  it("the summary counts the fresh offers when there are any", () => {
    const summary = summarizeOffers(
      [offer("old", 1, "in_stock", { ...old, shop: "shop-b" }), offer("a", 20)],
      now,
    );
    expect(summary).toMatchObject({ state: "in_stock", offerCount: 1, shopCount: 1, min: 20 });
  });

  it("the summary counts every offer when all are stale", () => {
    const summary = summarizeOffers(
      [offer("a", 1, "in_stock", old), offer("b", 20, "in_stock", { ...old, shop: "shop-b" })],
      now,
    );
    expect(summary).toMatchObject({ offerCount: 2, min: 1, max: 20 });
  });

  it("the primary button prefers a fresh offer to a cheaper stale one", () => {
    expect(primaryOffer([offer("old", 1, "in_stock", old), offer("a", 20)], now)?.id).toBe("a");
    expect(primaryOffer([offer("old", 1, "in_stock", old)], now)?.id).toBe("old");
  });
});
