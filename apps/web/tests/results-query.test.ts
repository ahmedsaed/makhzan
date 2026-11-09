import { describe, expect, it } from "vitest";

import type { SearchResponse } from "@/lib/api";
import {
  MAX_MIN_SUPPLIERS,
  activeFilterCount,
  apiParams,
  countText,
  flatParams,
  groupCategoryFacet,
  hiddenCounts,
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
      freshOnly: true,
      freshByDefault: true,
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
    const links = resultsLinks("/departments/tools", raw, parseResultsQuery(raw));
    expect(links.showOutOfStock).toBe("/departments/tools?q=relay&in_stock=all");
    expect(links.inStock).toBe("/departments/tools?q=relay&in_stock=all");
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

  it("works on any results path, so department and category pages share it", () => {
    const department = { q: "relay" };
    expect(resultsLinks("/departments/tools", department, parseResultsQuery(department)).twoShops).toBe(
      "/departments/tools?q=relay&min_suppliers=2",
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

  it("groups under departments, both largest first, and skips empty ones", () => {
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

describe("the stale filter (C2b)", () => {
  it("hides stale results when the URL says nothing, and shows them for stale=all", () => {
    expect(parseResultsQuery({ q: "relay" }).freshOnly).toBe(true);
    expect(parseResultsQuery({ q: "relay", stale: "all" }).freshOnly).toBe(false);
    expect(parseResultsQuery({ q: "relay", stale: "ALL" }).freshOnly).toBe(false);
    // Anything else is the default, not an error.
    expect(parseResultsQuery({ q: "relay", stale: "maybe" }).freshOnly).toBe(true);
  });

  it("follows the page's default, which stale=hide and stale=all override", () => {
    const shown = { freshByDefault: false };
    expect(parseResultsQuery({}, shown).freshOnly).toBe(false);
    expect(parseResultsQuery({ stale: "hide" }, shown).freshOnly).toBe(true);
    expect(parseResultsQuery({ stale: "all" }, shown).freshOnly).toBe(false);
  });

  it("sends fresh to the API explicitly, whose own default is everything", () => {
    expect(apiParams(parseResultsQuery({ q: "relay" })).fresh).toBe(true);
    expect(apiParams(parseResultsQuery({ q: "relay", stale: "all" })).fresh).toBe(false);
  });

  it("is independent of the stock filter", () => {
    const query = parseResultsQuery({ in_stock: "all" });
    expect(query).toMatchObject({ inStockOnly: false, freshOnly: true });
    expect(activeFilterCount(query)).toBe(0);
  });

  it("links: the chip toggles the parameter, and paging is dropped", () => {
    const raw = { q: "relay", offset: "24" };
    const links = resultsLinks("/search", raw, parseResultsQuery(raw));
    expect(links.fresh).toBe("/search?q=relay&stale=all");
    expect(links.showStale).toBe("/search?q=relay&stale=all");
    expect(links.showEverything).toBe("/search?q=relay&in_stock=all&stale=all");

    const off = { q: "relay", stale: "all" };
    expect(resultsLinks("/search", off, parseResultsQuery(off)).fresh).toBe("/search?q=relay");
  });

  it("links on a page that shows stale by default: the chip asks for stale=hide", () => {
    const shop = (raw: Record<string, string>) =>
      resultsLinks("/shops/shop-a", raw, parseResultsQuery(raw, { freshByDefault: false }));
    expect(shop({}).fresh).toBe("/shops/shop-a?stale=hide");
    expect(shop({ stale: "hide" }).fresh).toBe("/shops/shop-a");
  });
});

describe("hiddenCounts", () => {
  const response = (inStock: { true?: number; false?: number }): SearchResponse => ({
    query: "",
    identifier_query: false,
    total: (inStock.true ?? 0) + (inStock.false ?? 0),
    limit: 1,
    offset: 0,
    hits: [],
    facets: { in_stock: inStock },
  });

  // 100 match. In stock and fresh: 40. Out of stock and fresh: 10. In stock
  // and stale: 30. Out of stock and stale: 20.
  const main = response({ true: 40 });
  const unfiltered = response({ true: 40, false: 10 }); // fresh, any stock
  const everything = response({ true: 70, false: 30 }); // any stock, any age

  it("counts what each click adds, and the overlap apart", () => {
    const query = parseResultsQuery({ q: "relay" });
    expect(hiddenCounts(query, { result: main, unfiltered, everything, wide: main })).toEqual({
      outOfStock: 10,
      stale: 30,
      both: 20,
    });
  });

  it("with out of stock shown, every stale result is one click away", () => {
    const query = parseResultsQuery({ q: "relay", in_stock: "all" });
    const result = response({ true: 40, false: 10 });
    expect(
      hiddenCounts(query, { result, unfiltered: null, everything, wide: result }),
    ).toEqual({ outOfStock: 0, stale: 50, both: 0 });
  });

  it("with stale shown, only the stock count is left", () => {
    const query = parseResultsQuery({ q: "relay", stale: "all" });
    const result = response({ true: 70 });
    const all = response({ true: 70, false: 30 });
    expect(
      hiddenCounts(query, { result, unfiltered: all, everything: null, wide: result }),
    ).toEqual({ outOfStock: 30, stale: 0, both: 0 });
  });

  it("an empty page whose matches are all out of stock and out of date", () => {
    const query = parseResultsQuery({ q: "relay" });
    const none = response({});
    expect(
      hiddenCounts(query, {
        result: none,
        unfiltered: none,
        everything: response({ false: 7 }),
        wide: none,
      }),
    ).toEqual({ outOfStock: 0, stale: 0, both: 7 });
  });

  it("degrades to nothing hidden when a count search failed", () => {
    const query = parseResultsQuery({ q: "relay" });
    expect(
      hiddenCounts(query, { result: main, unfiltered: null, everything: null, wide: main }),
    ).toEqual({ outOfStock: 0, stale: 0, both: 0 });
  });
});
