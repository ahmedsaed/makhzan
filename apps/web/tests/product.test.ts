import { describe, expect, it } from "vitest";

import type { Category, Offer, Product, StockSignal } from "@/lib/api";
import {
  categoryTrail,
  galleryImages,
  jsonLdText,
  orderOffers,
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
    expect(summary).toEqual({
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

  it("walks trade › group › category, every crumb a link", () => {
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

  // makhzan compares other shops' offers; it sells nothing. An Offer would make
  // Google read the page as a merchant listing and ask for shipping, returns
  // and a GTIN (Search Console did, November 2026).
  it("is an AggregateOffer even for one shop, never an Offer", () => {
    const data = productJsonLd(product([offer("a", 850)]), URL, "Caliper", "A caliper.");
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

  it("spans several shops, leaving out offers without a price", () => {
    const data = productJsonLd(
      product([offer("a", 300, "out_of_stock"), offer("b", 260), offer("c", null)]),
      URL,
      "Board",
    );
    expect(data.offers).toMatchObject({
      "@type": "AggregateOffer",
      priceCurrency: "EGP",
      lowPrice: 260,
      highPrice: 300,
      offerCount: 2,
      availability: "https://schema.org/InStock",
    });
    expect(data.offers).not.toHaveProperty("offers");
  });

  it("is out of stock only when every priced offer is", () => {
    const data = productJsonLd(product([offer("a", 300, "out_of_stock")]), URL, "Board");
    expect(data.offers).toMatchObject({ availability: "https://schema.org/OutOfStock" });
  });

  it("clamps a long description at a word, and leaves out an empty one", () => {
    const long = productJsonLd(product([offer("a", 1)]), URL, "x", "word ".repeat(200));
    expect((long.description as string).length).toBeLessThanOrEqual(500);
    expect(long.description).toMatch(/word…$/);
    expect(productJsonLd(product([offer("a", 1)]), URL, "x", "  ")).not.toHaveProperty(
      "description",
    );
  });

  it("states no offer at all rather than a price of zero", () => {
    expect(productJsonLd(product([offer("a", null)]), URL, "x")).not.toHaveProperty("offers");
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
