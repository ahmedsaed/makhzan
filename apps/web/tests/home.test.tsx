import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Category, SearchResponse, ShopSummary, Stats } from "@/lib/api";
import { EXAMPLE_SEARCHES, exampleHref, tradeCards } from "@/lib/home";

const cat = (
  domain: string,
  slug: string,
  name_en: string,
  parent: string | null,
  count: number,
): Category => ({
  ref: `${domain}:${slug}`,
  domain,
  slug,
  name_en,
  name_ar: null,
  parent: parent ? `${domain}:${parent}` : null,
  count,
});

const CATEGORIES = [
  cat("seals-bearings", "seals", "Seals & Gaskets", null, 0),
  cat("seals-bearings", "o-rings", "O-Rings", "seals", 400),
  cat("seals-bearings", "oil-seals", "Oil Seals", "seals", 250),
  cat("seals-bearings", "seals-other", "Other Seals", "seals", 500),
  cat("seals-bearings", "bearings", "Bearings", null, 300),
  cat("seals-bearings", "empty", "Empty", null, 0),
  cat("tools", "calipers", "Calipers", null, 30),
  cat("garden", "nothing", "Nothing Yet", null, 0),
];

describe("tradeCards", () => {
  it("lists trades largest first with their biggest leaf categories as links", () => {
    const cards = tradeCards(CATEGORIES);
    expect(cards.map((card) => card.domain)).toEqual(["seals-bearings", "tools"]);
    // Leaves only, biggest first; "Other" and empty categories are left out.
    expect(cards[0].categories.map((c) => c.ref)).toEqual([
      "seals-bearings:o-rings",
      "seals-bearings:bearings",
      "seals-bearings:oil-seals",
    ]);
    expect(cards[0]).toMatchObject({ label: "Seals & Bearings", count: 1450 });
  });

  it("caps the categories per trade", () => {
    expect(tradeCards(CATEGORIES, 1)[0].categories).toHaveLength(1);
  });
});

describe("example searches", () => {
  it("link to the same URL the search field submits", () => {
    expect(exampleHref("relay module")).toBe("/search?q=relay+module");
    expect(new Set(EXAMPLE_SEARCHES).size).toBe(EXAMPLE_SEARCHES.length);
  });
});

// --------------------------------------------------------------------------- //
// The page fails soft, one section at a time
// --------------------------------------------------------------------------- //

const api = vi.hoisted(() => ({
  fetchCategories: vi.fn<() => Promise<Category[]>>(),
  fetchStats: vi.fn<() => Promise<Stats>>(),
  fetchSuppliers: vi.fn<() => Promise<ShopSummary[]>>(),
  searchProducts: vi.fn<() => Promise<SearchResponse>>(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  ...api,
}));

const SHOP: ShopSummary = {
  slug: "shop-a",
  name: "Shop A",
  name_ar: null,
  website_url: null,
  listing_count: 120,
  in_stock_count: 80,
  last_verified_at: new Date().toISOString(),
  domains: [{ domain: "tools", count: 120 }],
};

const SEVERAL: SearchResponse = {
  query: "",
  identifier_query: false,
  total: 42,
  limit: 6,
  offset: 0,
  hits: [
    {
      id: "p1",
      domain: "tools",
      part_number: null,
      title_en: "Digital Caliper 150 mm",
      title_ar: null,
      brand: null,
      category_slug: "calipers",
      category_ref: "tools:calipers",
      category_name: "Calipers",
      supplier_name: null,
      supplier_count: 3,
      offer_count: 3,
      min_price: 260,
      max_price: 400,
      currency: "EGP",
      in_stock: true,
      image: null,
      last_verified_at: Math.floor(Date.now() / 1000),
    },
  ],
};

async function renderHome() {
  const { default: HomePage } = await import("@/app/page");
  render(await HomePage());
}

const section = (name: string) => document.querySelector(`[data-home-section="${name}"]`);

describe("home page", () => {
  beforeEach(() => {
    api.fetchCategories.mockResolvedValue(CATEGORIES);
    api.fetchStats.mockResolvedValue({ products: 1450, suppliers: 1, categories: 8 });
    api.fetchSuppliers.mockResolvedValue([SHOP, { ...SHOP, slug: "empty", listing_count: 0 }]);
    api.searchProducts.mockResolvedValue(SEVERAL);
  });

  it("asks the API only for products sold by two or more shops, in stock", async () => {
    await renderHome();
    expect(api.searchProducts).toHaveBeenCalledWith(
      expect.objectContaining({ minSuppliers: 2, inStock: true }),
    );
    expect(section("several-shops")).toHaveTextContent("42 products in stock");
    expect(section("several-shops")).toHaveTextContent("EGP 260 – 400");
    // A shop with nothing listed sends a visitor nowhere.
    expect(document.querySelectorAll("[data-home-shop]")).toHaveLength(1);
  });

  it("links a trade's categories through the trade", async () => {
    await renderHome();
    const link = screen.getAllByRole("link", { name: /^O-Rings/ })[0];
    expect(link).toHaveAttribute("href", "/departments/seals-bearings/o-rings");
  });

  it("leaves out each section whose fetch failed and keeps the search", async () => {
    api.fetchCategories.mockRejectedValue(new Error("down"));
    api.fetchStats.mockRejectedValue(new Error("down"));
    api.fetchSuppliers.mockRejectedValue(new Error("down"));
    api.searchProducts.mockRejectedValue(new Error("down"));
    await renderHome();
    expect(section("trades")).toBeNull();
    expect(section("several-shops")).toBeNull();
    expect(section("shops")).toBeNull();
    expect(screen.getByRole("searchbox")).toBeInTheDocument();
    // Neither of these needs the API.
    expect(section("how")).not.toBeNull();
    expect(section("for-suppliers")).not.toBeNull();
  });

  it("drops the strip when no product has several shops", async () => {
    api.searchProducts.mockResolvedValue({ ...SEVERAL, total: 0, hits: [] });
    await renderHome();
    expect(section("several-shops")).toBeNull();
    expect(section("trades")).not.toBeNull();
  });
});
