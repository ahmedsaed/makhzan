import { describe, expect, it } from "vitest";

import { joinRef, routes, splitRef, switchLangPath } from "@/lib/routes";

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
  it("puts the language first on every URL", () => {
    expect(routes.home("ar")).toBe("/ar");
    expect(routes.product("en", "abc")).toBe("/en/products/abc");
    expect(routes.supplier("ar", "shop-a")).toBe("/ar/suppliers/shop-a");
  });

  it("addresses a category by its two segments, never the bare slug", () => {
    expect(routes.category("en", "electronics:resistors")).toBe("/en/browse/electronics/resistors");
    // The same slug in another domain is a different URL — that is the point.
    expect(routes.category("en", "tools:measurement")).not.toBe(
      routes.category("en", "electronics:measurement"),
    );
  });

  it("falls back to a search when handed a bare slug", () => {
    // Honest: we cannot tell which domain was meant, so we do not invent one.
    expect(routes.category("en", "measurement")).toBe("/en/search?category=measurement");
  });

  it("drops empty and false parameters instead of encoding them", () => {
    expect(routes.search("en", { q: "", inStock: false, offset: 0 })).toBe("/en/search");
    expect(routes.search("en", { q: "LM358", inStock: true })).toBe(
      "/en/search?q=LM358&in_stock=true",
    );
  });
});

describe("switching language", () => {
  it("keeps the reader on the same page", () => {
    expect(switchLangPath("/en/products/abc", "ar")).toBe("/ar/products/abc");
    expect(switchLangPath("/ar/browse/tools/saws", "en")).toBe("/en/browse/tools/saws");
  });

  it("handles the bare language root", () => {
    expect(switchLangPath("/en", "ar")).toBe("/ar");
  });

  it("does not mangle a path that merely starts with those letters", () => {
    expect(switchLangPath("/en/enclosures", "ar")).toBe("/ar/enclosures");
  });
});
