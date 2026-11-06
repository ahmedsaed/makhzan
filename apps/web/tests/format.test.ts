import { describe, expect, it } from "vitest";

import { formatPrice, formatPriceRange, plural } from "@/lib/format";
import { shopUrl } from "@/lib/shop-url";

describe("prices", () => {
  it("puts the currency first", () => {
    expect(formatPrice(850)).toBe("EGP 850");
  });

  it("keeps a fractional price exact — a resistor is 3.50, not 4", () => {
    expect(formatPrice(3.5)).toBe("EGP 3.50");
  });

  it("does not invent decimals on a whole price", () => {
    expect(formatPrice(350)).toBe("EGP 350");
  });

  it("groups thousands", () => {
    expect(formatPrice(39000)).toBe("EGP 39,000");
  });

  it("uses whatever currency the supplier published", () => {
    // Supplier data is not guaranteed to be a valid ISO code.
    expect(formatPrice(10, "ZZZ")).toBe("ZZZ 10");
  });
});

describe("price ranges (rule C3)", () => {
  it("reads 'EGP 260 – 400', the currency once", () => {
    expect(formatPriceRange(260, 400)).toBe("EGP 260 – 400");
    expect(formatPriceRange(850, 1450)).toBe("EGP 850 – 1,450");
  });

  it("collapses to one price when the ends agree", () => {
    expect(formatPriceRange(850, 850)).toBe("EGP 850");
  });

  it("shows the one price it has when an end is missing", () => {
    expect(formatPriceRange(850, null)).toBe("EGP 850");
    expect(formatPriceRange(null, 400)).toBe("EGP 400");
    expect(formatPriceRange(850)).toBe("EGP 850");
  });

  it("says 'Price on request' with no price, never zero", () => {
    expect(formatPriceRange(null, null)).toBe("Price on request");
    expect(formatPriceRange(undefined, undefined)).toBe("Price on request");
  });

  it("does not mistake a free item for a missing price", () => {
    expect(formatPriceRange(0, 0)).toBe("EGP 0");
  });
});

describe("counts", () => {
  it("pluralises", () => {
    expect(plural(1, "shop")).toBe("1 shop");
    expect(plural(3, "shop")).toBe("3 shops");
    expect(plural(1200, "product")).toBe("1,200 products");
  });
});

describe("links to shops carry ref=makhzan (rule P4)", () => {
  it("adds the tag", () => {
    expect(shopUrl("https://shop-a.test/p/esp32")).toBe("https://shop-a.test/p/esp32?ref=makhzan");
  });

  it("keeps the shop's own parameters", () => {
    expect(shopUrl("https://shop-a.test/p?id=12&variant=3")).toBe(
      "https://shop-a.test/p?id=12&variant=3&ref=makhzan",
    );
  });

  it("keeps the fragment after the query", () => {
    expect(shopUrl("https://shop-a.test/p?id=1#specs")).toBe(
      "https://shop-a.test/p?id=1&ref=makhzan#specs",
    );
  });

  it("does not add the tag twice", () => {
    expect(shopUrl("https://shop-a.test/p?ref=makhzan")).toBe("https://shop-a.test/p?ref=makhzan");
  });

  it("leaves a URL it cannot parse as it was", () => {
    expect(shopUrl("not a url")).toBe("not a url");
  });
});
