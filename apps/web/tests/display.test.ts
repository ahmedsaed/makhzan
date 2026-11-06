import { describe, expect, it } from "vitest";

import { hitFromSummary, titleOf } from "@/lib/api";
import type { Category, ProductSummary } from "@/lib/api";
import { tradeLabel, tradesFrom } from "@/lib/trades";

const category = (over: Partial<Category>): Category => ({
  ref: "electronics:resistors",
  domain: "electronics",
  slug: "resistors",
  name_en: "Resistors",
  name_ar: "مقاومات",
  parent: null,
  count: 0,
  ...over,
});

describe("supplier prose falls back rather than rendering empty", () => {
  it("prefers the English title", () => {
    expect(titleOf({ title_en: "LM358", title_ar: "إل إم" })).toBe("LM358");
  });

  it("shows an Arabic-only title as published rather than nothing", () => {
    // The interface is English, but a listing is evidence about a shop's
    // shelf and is never translated or hidden.
    expect(titleOf({ title_en: null, title_ar: "مقاومة" })).toBe("مقاومة");
    expect(titleOf({ title_en: null, title_ar: null })).toBe("");
  });
});

describe("trades are rolled up from categories", () => {
  it("sums each trade's categories and orders by size", () => {
    const trades = tradesFrom([
      category({ ref: "electronics:a", domain: "electronics", count: 10 }),
      category({ ref: "electronics:b", domain: "electronics", count: 5 }),
      category({ ref: "tools:c", domain: "tools", count: 20 }),
    ]);
    expect(trades.map((t) => [t.domain, t.count])).toEqual([
      ["tools", 20],
      ["electronics", 15],
    ]);
  });

  it("titles a slug", () => {
    expect(tradeLabel("seals-bearings")).toBe("Seals & Bearings");
    expect(tradeLabel("electronics")).toBe("Electronics");
  });
});

describe("a product summary renders as a search hit", () => {
  const summary = {
    id: "2",
    part_number: null,
    title_en: "Servo",
    title_ar: null,
    brand: null,
    image: null,
    supplier_count: 1,
    offer_count: 1,
    min_price: 62,
    max_price: 62,
    currency: "EGP",
    in_stock: false,
    last_verified_at: "2026-09-01T10:00:00Z",
    category: {
      ref: "electronics:motors",
      domain: "electronics",
      slug: "motors",
      name_en: "Motors",
      name_ar: null,
    },
  } satisfies ProductSummary;

  it("converts the ISO timestamp to the index's epoch seconds", () => {
    expect(hitFromSummary(summary).last_verified_at).toBe(
      Date.parse("2026-09-01T10:00:00Z") / 1000,
    );
    expect(hitFromSummary({ ...summary, last_verified_at: null }).last_verified_at).toBeNull();
  });

  it("carries the category and the shop when the caller knows it", () => {
    const hit = hitFromSummary(summary, "Shop A");
    expect(hit.category_ref).toBe("electronics:motors");
    expect(hit.domain).toBe("electronics");
    expect(hit.supplier_name).toBe("Shop A");
  });

  it("keeps a null price null rather than turning it into zero", () => {
    // "Price on request" must never sort or display as free.
    expect(hitFromSummary({ ...summary, min_price: null, max_price: null }).min_price).toBeNull();
  });
});
