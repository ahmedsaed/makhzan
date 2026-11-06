import { describe, expect, it } from "vitest";

import {
  MAX_MIN_SUPPLIERS,
  apiParams,
  countText,
  flatParams,
  groupCategoryFacet,
  hiddenOutOfStock,
  parseResultsQuery,
  resultsLinks,
  topCategories,
} from "@/lib/results-query";

describe("parseResultsQuery", () => {
  it("shows in stock only when the URL says nothing (C2)", () => {
    expect(parseResultsQuery({ q: "relay" }).inStockOnly).toBe(true);
    expect(parseResultsQuery({ q: "relay", in_stock: "true" }).inStockOnly).toBe(true);
  });

  it("shows everything for in_stock=all, and for the older in_stock=false", () => {
    expect(parseResultsQuery({ in_stock: "all" }).inStockOnly).toBe(false);
    expect(parseResultsQuery({ in_stock: "false" }).inStockOnly).toBe(false);
  });

  it("sends in stock to the API explicitly, whose own default is everything", () => {
    expect(apiParams(parseResultsQuery({ q: "relay" })).inStock).toBe(true);
    expect(apiParams(parseResultsQuery({ q: "relay", in_stock: "all" })).inStock).toBe(false);
  });

  it("drops malformed values rather than passing them on", () => {
    const query = parseResultsQuery({
      q: "  relay ",
      min_price: "cheap",
      max_price: "-4",
      min_suppliers: "1",
      sort: "title:asc",
      offset: "-24",
      category: "",
    });
    expect(query).toEqual({
      q: "relay",
      category: undefined,
      domain: undefined,
      shop: undefined,
      inStockOnly: true,
      minSuppliers: undefined,
      minPrice: undefined,
      maxPrice: undefined,
      sort: undefined,
      offset: 0,
    });
  });

  it("reads filters, and swaps a reversed price range", () => {
    const query = parseResultsQuery({
      q: "relay",
      category: "electronics:ics",
      shop: "shop-a",
      min_suppliers: "2",
      min_price: "500",
      max_price: "100",
      sort: "price:asc",
      offset: "24",
    });
    expect(query).toMatchObject({
      category: "electronics:ics",
      shop: "shop-a",
      minSuppliers: 2,
      minPrice: 100,
      maxPrice: 500,
      sort: "price:asc",
      offset: 24,
    });
    expect(apiParams(query)).toMatchObject({ shop: "shop-a", minPrice: 100, maxPrice: 500 });
  });

  it("clamps min_suppliers to what the API accepts", () => {
    expect(parseResultsQuery({ min_suppliers: "500" }).minSuppliers).toBe(MAX_MIN_SUPPLIERS);
    expect(parseResultsQuery({ min_suppliers: "50" }).minSuppliers).toBe(50);
    expect(parseResultsQuery({ min_suppliers: "3" }).minSuppliers).toBe(3);
    expect(parseResultsQuery({ min_suppliers: "0" }).minSuppliers).toBeUndefined();
    expect(MAX_MIN_SUPPLIERS).toBe(50);
  });

  it("links to everything with in_stock=all, the one way to say it", () => {
    const raw = { q: "relay" };
    const links = resultsLinks("/trades/tools", raw, parseResultsQuery(raw));
    expect(links.showOutOfStock).toBe("/trades/tools?q=relay&in_stock=all");
    expect(links.inStock).toBe("/trades/tools?q=relay&in_stock=all");
  });

  it("counts what the stock filter shows in its own words", () => {
    expect(countText(1234, true)).toBe("1,234 in stock");
    expect(countText(1, false)).toBe("1 result");
    expect(countText(36, false)).toBe("36 results");
  });

  it("takes the first of a repeated parameter", () => {
    expect(parseResultsQuery({ q: ["a", "b"] }).q).toBe("a");
  });
});

describe("hiddenOutOfStock", () => {
  it("reads the out-of-stock count from the unfiltered facet", () => {
    expect(hiddenOutOfStock({ in_stock: { true: 85, false: 51 } })).toBe(51);
  });

  it("is zero when nothing is out of stock or the count is unknown", () => {
    expect(hiddenOutOfStock({ in_stock: { true: 85 } })).toBe(0);
    expect(hiddenOutOfStock(undefined)).toBe(0);
  });
});

describe("resultsLinks", () => {
  const raw = { q: "relay", offset: "24" };
  const links = resultsLinks("/search", raw, parseResultsQuery(raw));

  it("turns in stock off with in_stock=all and back on by removing it", () => {
    expect(links.inStock).toBe("/search?q=relay&in_stock=all");
    const off = { q: "relay", in_stock: "all" };
    expect(resultsLinks("/search", off, parseResultsQuery(off)).inStock).toBe("/search?q=relay");
  });

  it("toggles 2+ shops", () => {
    expect(links.twoShops).toBe("/search?q=relay&min_suppliers=2");
    const on = { q: "relay", min_suppliers: "2" };
    expect(resultsLinks("/search", on, parseResultsQuery(on)).twoShops).toBe("/search?q=relay");
  });

  it("drops the page when a filter changes, and keeps it only for paging", () => {
    expect(links.showOutOfStock).toBe("/search?q=relay&in_stock=all");
    expect(links.category("tools:measurement")).toBe(
      "/search?q=relay&category=tools%3Ameasurement",
    );
    expect(links.page(48)).toBe("/search?q=relay&offset=48");
    expect(links.page(0)).toBe("/search?q=relay");
  });

  it("works on any results path, so trade and category pages share it", () => {
    const trade = { q: "relay" };
    expect(resultsLinks("/trades/tools", trade, parseResultsQuery(trade)).twoShops).toBe(
      "/trades/tools?q=relay&min_suppliers=2",
    );
  });
});

describe("category facets", () => {
  const facet = {
    "electronics:ics": 40,
    "tools:measurement": 70,
    "electronics:resistors": 50,
    "electronics:empty": 0,
  };

  it("groups under trades, both largest first, and skips empty ones", () => {
    expect(groupCategoryFacet(facet)).toEqual([
      {
        domain: "electronics",
        count: 90,
        categories: [
          { ref: "electronics:resistors", count: 50 },
          { ref: "electronics:ics", count: 40 },
        ],
      },
      { domain: "tools", count: 70, categories: [{ ref: "tools:measurement", count: 70 }] },
    ]);
  });

  it("picks the top three for the query", () => {
    expect(topCategories(facet).map((c) => c.ref)).toEqual([
      "tools:measurement",
      "electronics:resistors",
      "electronics:ics",
    ]);
  });
});

describe("flatParams", () => {
  it("keeps first values, drops empties and omitted keys", () => {
    expect(
      flatParams({ q: "relay", sort: "", offset: "24", shop: ["a", "b"] }, ["offset"]),
    ).toEqual({ q: "relay", shop: "a" });
  });
});
