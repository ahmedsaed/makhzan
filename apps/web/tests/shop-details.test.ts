/**
 * Which specs, datasheets and brand the product page shows (rule C4): one
 * shop's at a time, never merged across shops, and nothing at all when no
 * shop published any.
 */
import { describe, expect, it } from "vitest";

import type { Offer, Product, StockSignal } from "@/lib/api";
import {
  brandOf,
  datasheetLabel,
  detailSources,
  isPartNumberSpec,
  leadOffer,
  primaryOffer,
  shopDetails,
} from "@/lib/product";

function offer(
  id: string,
  price: number | null,
  stock: StockSignal,
  extra: Partial<Offer> = {},
): Offer {
  return {
    id,
    title_en: `Offer ${id}`,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: `https://shop-${id}.test/p/${id}`,
    images: [],
    last_verified_at: "2026-11-01T00:00:00Z",
    supplier: {
      id: `sup-${id}`,
      slug: `shop-${id}`,
      name: `Shop ${id.toUpperCase()}`,
      name_ar: null,
      area: null,
      governorate: null,
      website_url: null,
    },
    ...extra,
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
    supplier_count: offers.length,
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

const SPECS = { "Operating Voltage": "5V", Range: "0-200 mm" };
const DOCS = [{ url: "https://shop-a.test/files/meter.pdf", label: "User manual" }];

describe("the lead offer's details", () => {
  it("are the primary offer's, the one the bottom bar opens", () => {
    // The cheapest offer is out of stock, so the in-stock one leads.
    const cheap = offer("a", 100, "out_of_stock", { specs: { Range: "0-100 mm" } });
    const lead = offer("b", 150, "in_stock", { specs: SPECS, documents: DOCS });
    const item = product([cheap, lead]);

    expect(primaryOffer(item.offers)?.id).toBe("b");
    expect(leadOffer(item.offers)?.id).toBe("b");
    const details = shopDetails(item);
    expect(details?.offer.id).toBe("b");
    expect(details?.shopName).toBe("Shop B");
    expect(details?.specs.map((row) => [row.name, row.value])).toEqual([
      ["Operating Voltage", "5V"],
      ["Range", "0-200 mm"],
    ]);
    expect(details?.datasheets).toEqual([
      { url: "https://shop-a.test/files/meter.pdf", label: "User manual" },
    ]);
  });

  it("are never borrowed from another shop when the lead has none", () => {
    const lead = offer("a", 100, "in_stock");
    const other = offer("b", 150, "in_stock", { specs: SPECS, documents: DOCS });
    expect(shopDetails(product([lead, other]))).toBeNull();
  });

  it("are nothing when the shop published nothing, or the API predates them", () => {
    expect(shopDetails(product([offer("a", 1, "in_stock", { specs: {}, documents: [] })]))).toBe(
      null,
    );
    expect(shopDetails(product([offer("a", 1, "in_stock")]))).toBeNull();
  });

  it("keep one section when the other is empty", () => {
    const details = shopDetails(product([offer("a", 1, "in_stock", { documents: DOCS })]));
    expect(details?.specs).toEqual([]);
    expect(details?.datasheets).toHaveLength(1);
  });

  it("drop documents that are not web links", () => {
    const details = shopDetails(
      product([
        offer("a", 1, "in_stock", {
          documents: [{ url: "javascript:alert(1)", label: "x" }, ...DOCS],
        }),
      ]),
    );
    expect(details?.datasheets.map((doc) => doc.url)).toEqual([DOCS[0].url]);
  });
});

describe("spec rows", () => {
  it("set a part number in the monospace face, and nothing else", () => {
    expect(isPartNumberSpec("Model", "UT61E")).toBe(true);
    expect(isPartNumberSpec("Part Number", "LM2596S-ADJ")).toBe(true);
    expect(isPartNumberSpec("MPN", "ESP32-WROOM-32")).toBe(true);
    // Values that are measurements or prose stay plain.
    expect(isPartNumberSpec("Model", "Digital multimeter")).toBe(false);
    expect(isPartNumberSpec("Operating Voltage", "5V")).toBe(false);
    expect(isPartNumberSpec("Range", "0-200mm")).toBe(false);
  });
});

describe("datasheet labels", () => {
  it("use the shop's link text, else the file's name", () => {
    expect(datasheetLabel("https://shop-a.test/x.pdf", " Datasheet (EN) ")).toBe("Datasheet (EN)");
    expect(datasheetLabel("https://shop-a.test/docs/LM358%20sheet.pdf", null)).toBe(
      "LM358 sheet.pdf",
    );
    expect(datasheetLabel("https://shop-a.test/", null)).toBe("Datasheet");
  });
});

describe("brand", () => {
  it("is the product's, else the lead shop's, else unknown", () => {
    const lead = offer("a", 1, "in_stock", { brand: "Acme" });
    expect(brandOf(product([lead], { brand: "Zeta" }))).toBe("Zeta");
    expect(brandOf(product([lead]))).toBe("Acme");
    expect(brandOf(product([offer("a", 1, "in_stock")]))).toBeNull();
  });
});

describe('detailSources: the product page\'s "From" tabs', () => {
  const plain = offer("a", 100, "in_stock");
  const specced = offer("b", 120, "in_stock", { specs: { Voltage: "5V", Current: "2A" } });
  const sheeted = offer("c", 130, "in_stock", {
    documents: [{ url: "https://shop-c.test/ds.pdf", label: "Datasheet" }],
  });

  it("gives no tab to a shop that wrote nothing", () => {
    const sources = detailSources([plain, specced], new Map());
    expect(sources.map((s) => s.offer.id)).toEqual(["b"]);
  });

  it("puts the richest first, ties in the offers' own order", () => {
    const described = new Map([["a", "A long description. ".repeat(40)]]);
    const sources = detailSources([plain, specced, sheeted], described);
    // a: 2 + 1500/300 = 7; c: one datasheet = 3; b: two specs = 2.
    expect(sources.map((s) => s.offer.id)).toEqual(["a", "c", "b"]);
    expect(sources[0].description).toMatch(/^A long description/);
  });

  it("is empty when no shop wrote anything", () => {
    expect(detailSources([plain], new Map([["a", "   "]]))).toEqual([]);
  });

  it("numbers the tabs of one shop's several offers", () => {
    const one = offer("x", 100, "in_stock", { specs: { Pins: "30" } });
    const two = {
      ...offer("y", 110, "in_stock", { specs: { Pins: "38" } }),
      supplier: one.supplier,
    };
    const labels = detailSources([one, two], new Map()).map((s) => s.label);
    expect(labels).toEqual(["Shop X (1)", "Shop X (2)"]);
  });
});
