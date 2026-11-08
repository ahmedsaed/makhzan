import { describe, expect, it } from "vitest";

import { redirectTarget } from "@/lib/redirects";
import {
  joinRef,
  productIdFrom,
  productParam,
  routes,
  slugify,
  splitRef,
  withParams,
} from "@/lib/routes";

describe("category refs", () => {
  it("splits domain:slug", () => {
    expect(splitRef("electronics:resistors")).toEqual({
      domain: "electronics",
      slug: "resistors",
    });
  });

  it("refuses a bare slug, which names a category in every domain that uses it", () => {
    expect(splitRef("measurement")).toBeNull();
    expect(splitRef(":resistors")).toBeNull();
    expect(splitRef("electronics:")).toBeNull();
  });

  it("round-trips", () => {
    expect(splitRef(joinRef("tools", "measurement"))).toEqual({
      domain: "tools",
      slug: "measurement",
    });
  });
});

describe("routes", () => {
  it("has no language in any URL", () => {
    expect(routes.home()).toBe("/");
    expect(routes.product("abc")).toBe("/products/abc");
    expect(routes.shop("shop-a")).toBe("/shops/shop-a");
    expect(routes.trade("electronics")).toBe("/trades/electronics");
  });

  it("addresses a category through its trade, never by the bare slug", () => {
    expect(routes.category("electronics:resistors")).toBe("/trades/electronics/resistors");
    // The same slug in another trade is a different URL — that is the point.
    expect(routes.category("tools:measurement")).not.toBe(
      routes.category("electronics:measurement"),
    );
  });

  it("falls back to a search when handed a bare slug", () => {
    // Honest: we cannot tell which trade was meant, so we do not invent one.
    expect(routes.category("measurement")).toBe("/search?category=measurement");
  });
});

describe("withParams", () => {
  it("sets and removes parameters, keeping the rest", () => {
    expect(withParams("/search", { q: "esp32" }, { in_stock: "true" })).toBe(
      "/search?q=esp32&in_stock=true",
    );
    expect(withParams("/search", { q: "esp32", in_stock: "true" }, { in_stock: null })).toBe(
      "/search?q=esp32",
    );
  });

  it("drops the page, which means nothing once the result set changes", () => {
    expect(withParams("/search", { q: "a", offset: "48" }, { sort: "price:asc" })).toBe(
      "/search?q=a&sort=price%3Aasc",
    );
  });

  it("returns the bare path when nothing is left", () => {
    expect(withParams("/search", new URLSearchParams("sort=x"), { sort: null })).toBe("/search");
  });
});

describe("old URLs", () => {
  it("lose their language prefix", () => {
    expect(redirectTarget("/en")).toBe("/");
    expect(redirectTarget("/ar")).toBe("/");
    expect(redirectTarget("/en/products/abc")).toBe("/products/abc");
    expect(redirectTarget("/ar/search")).toBe("/search");
  });

  it("map the old names onto the new, with or without a prefix, in one hop", () => {
    expect(redirectTarget("/en/browse/tools")).toBe("/trades/tools");
    expect(redirectTarget("/browse/tools/saws")).toBe("/trades/tools/saws");
    expect(redirectTarget("/ar/suppliers/shop-a")).toBe("/shops/shop-a");
    expect(redirectTarget("/suppliers/shop-a")).toBe("/shops/shop-a");
  });

  it("leave current URLs, and lookalikes, alone", () => {
    expect(redirectTarget("/trades/tools")).toBeNull();
    expect(redirectTarget("/search")).toBeNull();
    // Starts with the letters, is not the prefix.
    expect(redirectTarget("/enclosures")).toBeNull();
    expect(redirectTarget("/browser")).toBeNull();
  });
});

describe("readable product URLs", () => {
  const ID = "6a1bc5c4-07fd-4995-a1f3-8d3380cf29c8";

  it("slugs a title into lowercase Latin words", () => {
    expect(slugify("MG90S Metal Gear Servo (180°)")).toBe("mg90s-metal-gear-servo-180");
    expect(slugify("Résistance 10kΩ ±5%")).toBe("resistance-10k-5");
    expect(slugify("فلتر زيت")).toBe("");
    expect(slugify(null)).toBe("");
  });

  it("cuts a long title at a word, within 60 characters", () => {
    const slug = slugify("word ".repeat(40));
    expect(slug.length).toBeLessThanOrEqual(60);
    expect(slug.endsWith("-word")).toBe(true);
  });

  it("puts the slug after a UUID, and only after a UUID", () => {
    expect(routes.product(ID, "Transformer 3A")).toBe(`/products/${ID}-transformer-3a`);
    expect(routes.product(ID, "فلتر")).toBe(`/products/${ID}`);
    expect(routes.product(ID)).toBe(`/products/${ID}`);
    expect(productParam("p-multi", "ESP32 Board")).toBe("p-multi");
  });

  it("splits the id back off, slug or not", () => {
    expect(productIdFrom(`${ID}-transformer-3a`)).toBe(ID);
    expect(productIdFrom(ID)).toBe(ID);
    expect(productIdFrom(ID.toUpperCase())).toBe(ID.toUpperCase());
    expect(productIdFrom("p-multi")).toBe("p-multi");
  });
});
