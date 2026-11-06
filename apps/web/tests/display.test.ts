import { describe, expect, it } from "vitest";

import { categoryNameOf, supplierNameOf, titleOf } from "@/lib/api";
import { labelFor, verticalsFrom } from "@/components/browse-menu";
import { rowFromHit, rowFromSummary } from "@/components/product-row";
import type { Category, ProductSummary, SearchHit } from "@/lib/api";

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
  it("prefers the reader's language", () => {
    expect(titleOf({ title_en: "LM358", title_ar: "إل إم" }, "ar")).toBe("إل إم");
    expect(titleOf({ title_en: "LM358", title_ar: "إل إم" }, "en")).toBe("LM358");
  });

  it("uses whatever the supplier did publish when the other language is missing", () => {
    // Titles are supplier prose, so a language is often simply absent.
    expect(titleOf({ title_en: "LM358", title_ar: null }, "ar")).toBe("LM358");
    expect(titleOf({ title_en: null, title_ar: "مقاومة" }, "en")).toBe("مقاومة");
    expect(titleOf({ title_en: null, title_ar: null }, "en")).toBe("");
  });

  it("does the same for categories and suppliers", () => {
    expect(categoryNameOf(category({}), "ar")).toBe("مقاومات");
    expect(categoryNameOf(category({ name_ar: null }), "ar")).toBe("Resistors");
    expect(supplierNameOf({ name: "Shop A", name_ar: null } as never, "ar")).toBe("Shop A");
  });
});

describe("verticals are rolled up from categories", () => {
  it("sums each domain's categories and orders by size", () => {
    const verticals = verticalsFrom(
      [
        category({ ref: "electronics:a", domain: "electronics", count: 10 }),
        category({ ref: "electronics:b", domain: "electronics", count: 5 }),
        category({ ref: "tools:c", domain: "tools", count: 20 }),
      ],
      "en",
    );
    expect(verticals.map((v) => [v.domain, v.count])).toEqual([
      ["tools", 20],
      ["electronics", 15],
    ]);
  });

  it("titles a slug for English and uses authored Arabic", () => {
    expect(labelFor("seals-bearings", "en")).toBe("Seals & Bearings");
    expect(labelFor("electronics", "ar")).toBe("إلكترونيات");
    // An unknown domain still renders something rather than a blank tile.
    expect(labelFor("brand-new", "ar")).toBe("Brand & New");
  });
});

describe("rows", () => {
  const hit: SearchHit = {
    id: "1",
    domain: "electronics",
    part_number: "LM358N",
    title_en: "LM358N Dual Op-Amp",
    title_ar: null,
    brand: "TI",
    category_slug: "ics",
    category_ref: "electronics:ics",
    category_name: "ICs",
    supplier_name: "Shop A",
    supplier_count: 3,
    offer_count: 3,
    min_price: 12.5,
    max_price: 20,
    currency: "EGP",
    in_stock: true,
    image: null,
    last_verified_at: 1_760_000_000,
  };

  it("reads the index's epoch-second timestamp as a date", () => {
    const row = rowFromHit(hit, "en");
    expect(row.verifiedAt).toEqual(new Date(1_760_000_000 * 1000));
  });

  it("tolerates a hit with no timestamp", () => {
    expect(rowFromHit({ ...hit, last_verified_at: null }, "en").verifiedAt).toBeNull();
  });

  it("falls back to the part number when a title is missing entirely", () => {
    expect(rowFromHit({ ...hit, title_en: null, title_ar: null }, "en").title).toBe("LM358N");
  });

  it("keeps a null price null rather than turning it into zero", () => {
    // "Price on request" must never sort or display as free.
    expect(rowFromHit({ ...hit, min_price: null }, "en").minPrice).toBeNull();
  });

  it("maps a product summary, whose timestamp is an ISO string", () => {
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
      category: null,
    } satisfies ProductSummary;
    const row = rowFromSummary(summary, "en", "note");
    expect(row.verifiedAt?.toISOString()).toBe("2026-09-01T10:00:00.000Z");
    expect(row.note).toBe("note");
  });
});
