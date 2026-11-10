import { describe, expect, it } from "vitest";

import type { Listing } from "@/lib/api";
import { CONTACT_EMAIL, mailtoHref, supplierRequests } from "@/lib/content/supplier-requests";
import {
  formatDay,
  hitFromListing,
  hostOf,
  isStale,
  listedShops,
  shopSearchUrl,
  departmentShares,
  departmentsInWords,
} from "@/lib/shops";

const NOW = new Date("2026-11-06T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW.getTime() - days * 86_400_000).toISOString();

describe("which shops are listed", () => {
  it("hides a shop with no active listings", () => {
    const shops = [{ listing_count: 3 }, { listing_count: 0 }, { listing_count: 1 }];
    expect(listedShops(shops)).toEqual([{ listing_count: 3 }, { listing_count: 1 }]);
  });
});

describe("a stale shop (F2, F3)", () => {
  it("is one last checked over 45 days ago", () => {
    expect(isStale(daysAgo(45), NOW)).toBe(false);
    expect(isStale(daysAgo(46), NOW)).toBe(true);
  });

  it("is not a shop never checked at all", () => {
    expect(isStale(null, NOW)).toBe(false);
  });
});

describe("shop text", () => {
  it("drops the scheme and www from the site", () => {
    expect(hostOf("https://www.shop-a.test/ar/")).toBe("shop-a.test");
    expect(hostOf("not a url")).toBe("not a url");
  });

  it("dates a check by day, adding the year only when it is not this one", () => {
    expect(formatDay(new Date("2026-08-23T10:00:00Z"), NOW)).toBe("23 Aug");
    expect(formatDay(new Date("2025-08-23T10:00:00Z"), NOW)).toBe("23 Aug 2025");
  });

  it("names the top departments in words", () => {
    const d = (domain: string) => ({ domain, count: 1 });
    expect(departmentsInWords([])).toBe("");
    expect(departmentsInWords([d("electronics")])).toBe("Electronics");
    expect(departmentsInWords([d("electronics"), d("seals-bearings")])).toBe(
      "Electronics and Seals & Bearings",
    );
    expect(departmentsInWords([d("a"), d("b"), d("c"), d("d"), d("e")])).toBe(
      "A, B, C and 2 more departments",
    );
  });
});

describe("the department bar", () => {
  it("shares add up, the tail folded into one segment", () => {
    const shares = departmentShares([
      { domain: "electronics", count: 70 },
      { domain: "tools", count: 10 },
      { domain: "chemicals", count: 10 },
      { domain: "piping", count: 5 },
      { domain: "safety", count: 5 },
    ]);
    expect(shares.map((s) => s.domain)).toEqual(["electronics", "tools", "chemicals", null]);
    expect(shares[3]).toMatchObject({ count: 10, label: "2 other departments 10" });
    expect(shares.reduce((sum, s) => sum + s.percent, 0)).toBeCloseTo(100);
  });

  it("does not fold a single department into 'others'", () => {
    const four = ["a", "b", "c", "d"].map((domain) => ({ domain, count: 1 }));
    expect(departmentShares(four).map((s) => s.domain)).toEqual(["a", "b", "c", "d"]);
  });

  it("draws nothing for an empty shop", () => {
    expect(departmentShares([])).toEqual([]);
  });
});

describe("searching a shop", () => {
  it("scopes /search to the shop, and optionally a category or department", () => {
    expect(shopSearchUrl("shop-a")).toBe("/search?shop=shop-a");
    expect(shopSearchUrl("shop-a", { category: "tools:measurement" })).toBe(
      "/search?shop=shop-a&category=tools%3Ameasurement",
    );
    expect(shopSearchUrl("shop-a", { domain: "tools" })).toBe("/search?shop=shop-a&domain=tools");
  });
});

describe("a shop's listing as a result", () => {
  const listing = {
    id: "l-1",
    product_id: "p-1",
    title_en: "LM358",
    title_ar: null,
    part_number: null,
    brand: null,
    price: 12.5,
    currency: "EGP",
    stock_signal: "in_stock",
    images: ["https://img.test/1.jpg"],
    last_verified_at: "2026-11-01T00:00:00Z",
    supplier: { name: "Shop A" },
    category: null,
  } as unknown as Listing;

  it("opens the product and names the shop (C1, P1)", () => {
    expect(hitFromListing(listing)).toMatchObject({
      id: "p-1",
      supplier_name: "Shop A",
      supplier_count: 1,
      min_price: 12.5,
      image: "https://img.test/1.jpg",
      last_verified_at: Date.parse("2026-11-01T00:00:00Z") / 1000,
    });
  });

  it("is dropped when it has no product to open", () => {
    expect(hitFromListing({ ...listing, product_id: null })).toBeNull();
  });
});

describe("supplier requests", () => {
  it("offers remove first, then add and correct", () => {
    expect(supplierRequests.map((r) => r.id)).toEqual(["remove", "add", "correct", "schedule"]);
  });

  it("promises removal within 7 days", () => {
    expect(supplierRequests[0].summary).toMatch(/within 7 days/);
  });

  it("builds a mailto with spaces encoded as %20, never +", () => {
    const href = mailtoHref("crawler@makhzan.merope.dev", {
      subject: "Remove my shop",
      body: "a\nb",
    });
    expect(href).toBe("mailto:crawler@makhzan.merope.dev?subject=Remove%20my%20shop&body=a%0Ab");
  });

  it.each(supplierRequests)("$id goes to the crawler's address with a subject and body", (r) => {
    const url = new URL(mailtoHref(CONTACT_EMAIL, r));
    expect(url.protocol).toBe("mailto:");
    expect(url.pathname).toBe("crawler@makhzan.merope.dev");
    expect(decodeURIComponent(url.search)).toContain(`subject=${r.subject}`);
    expect(r.body).toMatch(/Shop name:/);
  });
});
