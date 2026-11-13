import { afterEach, describe, expect, it, vi } from "vitest";

import type { Category, Offer, Product, StockSignal, SupplierProfile } from "@/lib/api";
import {
  breadcrumbJsonLd,
  pagedPath,
  categoryDescription,
  homeDescription,
  homeJsonLd,
  pageMetadata,
  productDescription,
  shopCardLines,
  shopDescription,
  totalsLine,
  departmentCardLines,
  departmentDescription,
} from "@/lib/metadata";
import { clampText } from "@/lib/og";
import { sitemapEntries } from "@/lib/sitemap";

function offer(id: string, price: number | null, shop: string, stock: StockSignal = "in_stock") {
  return {
    id,
    title_en: id,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: `https://${shop}.test/${id}`,
    images: [],
    last_verified_at: "2026-11-01T00:00:00Z",
    supplier: {
      id: shop,
      slug: shop,
      name: `Shop ${shop.toUpperCase()}`,
      name_ar: null,
      area: null,
      governorate: null,
      website_url: null,
    },
  } satisfies Offer;
}

function product(offers: Offer[], extra: Partial<Product> = {}): Product {
  return {
    id: "p1",
    part_number: null,
    title_en: "Digital Caliper 150mm",
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

const category = (
  domain: string,
  slug: string,
  name: string,
  count: number,
  parent: string | null = null,
): Category => ({
  ref: `${domain}:${slug}`,
  domain,
  slug,
  name_en: name,
  name_ar: null,
  parent,
  count,
});

const SEALS = [
  category("seals-bearings", "seals", "Seals", 0),
  category("seals-bearings", "o-rings", "O-Rings", 900, "seals-bearings:seals"),
  category("seals-bearings", "oil-seals", "Oil Seals", 400, "seals-bearings:seals"),
  category("seals-bearings", "bearings", "Bearings", 600),
  category("seals-bearings", "other", "Other Seals", 80),
  category("tools", "calipers", "Calipers", 50),
];

describe("productDescription", () => {
  it("states the price range and how many shops", () => {
    const text = productDescription(
      product([offer("a", 75, "a"), offer("b", 110, "b"), offer("c", 90, "c")]),
    );
    expect(text).toMatch(/^Digital Caliper 150mm: EGP 75 – 110 at 3 shops in Egypt\./);
  });

  it("names the shop when only one sells it", () => {
    expect(productDescription(product([offer("a", 850, "a")]))).toContain(
      "EGP 850 at Shop A in Egypt.",
    );
  });

  it("says so when every shop is out of stock", () => {
    const text = productDescription(
      product([offer("a", 40, "a", "out_of_stock"), offer("b", 50, "b", "out_of_stock")]),
    );
    expect(text).toContain("EGP 40 – 50 at 2 shops in Egypt, out of stock.");
  });

  it("falls back to the part number for a product with no title", () => {
    const text = productDescription(
      product([offer("a", null, "a")], { title_en: null, part_number: "LM358N" }),
    );
    expect(text).toMatch(/^LM358N: Price on request at Shop A/);
  });
});

describe("department and category descriptions", () => {
  it("counts a department's products and names its biggest categories, not 'Other'", () => {
    expect(departmentDescription("seals-bearings", SEALS)).toBe(
      "1,980 products in Seals & Bearings from Egypt's suppliers: O-Rings, bearings, oil seals. 4 categories, compared across shops.",
    );
  });

  it("has nothing to say about an empty or unknown department", () => {
    expect(departmentDescription("timber", SEALS)).toBeUndefined();
  });

  it("gives a department card its count, its size in categories, and three names", () => {
    expect(departmentCardLines("seals-bearings", SEALS)).toEqual({
      title: "Seals & Bearings",
      detail: "1,980 products · 4 categories",
      inside: ["O-Rings", "Bearings", "Oil Seals"],
    });
  });

  it("describes a category with its subtree's total, in its department", () => {
    expect(categoryDescription(SEALS[0], 1300)).toMatch(
      /^1,300 products in Seals \(Seals & Bearings\) from Egypt's suppliers/,
    );
  });
});

describe("shop descriptions", () => {
  const shop: SupplierProfile = {
    slug: "shop-a",
    name: "Shop A",
    name_ar: null,
    website_url: null,
    listing_count: 4340,
    in_stock_count: 3238,
    last_verified_at: null,
    domains: [{ domain: "electronics", count: 4340 }],
    area: null,
    governorate: null,
    top_categories: [
      { ref: "electronics:batteries", name_en: "Batteries", name_ar: null, count: 500 },
      { ref: "electronics:resistors", name_en: "Resistors", name_ar: null, count: 400 },
    ],
  };

  it("counts what the shop lists and has in stock, and what it carries", () => {
    expect(shopDescription(shop)).toMatch(
      /^4,340 products from Shop A, 3,238 in stock: Batteries, resistors\./,
    );
    expect(shopCardLines(shop)).toEqual({
      title: "Shop A",
      detail: "4,340 products · 3,238 in stock",
      carries: "Batteries, resistors and more",
    });
  });

  it("falls back to its departments when it has no categories", () => {
    expect(shopCardLines({ ...shop, top_categories: [] }).carries).toBe("Electronics");
  });
});

describe("site descriptions", () => {
  it("puts the totals on the site's card and home page", () => {
    const stats = { products: 59608, suppliers: 8, categories: 243 };
    expect(totalsLine(stats)).toBe("59,608 products · 8 shops · rechecked weekly");
    expect(homeDescription(stats)).toMatch(
      /^Find parts and materials across Egypt's suppliers\. 59,608 products from 8 shops,/,
    );
  });

  it("still says what the site is when the API does not answer", () => {
    expect(homeDescription(null)).toMatch(/^Find parts and materials across Egypt's suppliers/);
  });
});

describe("pageMetadata", () => {
  it("keeps title, description and canonical in step with the preview", () => {
    const meta = pageMetadata({
      title: "Tools",
      description: "Hand tools.",
      path: "/departments/tools",
    });
    expect(meta.title).toBe("Tools");
    expect(meta.alternates?.canonical).toBe("/departments/tools");
    expect(meta.openGraph).toMatchObject({
      title: "Tools · makhzan",
      description: "Hand tools.",
      url: "/departments/tools",
      siteName: "makhzan",
      locale: "en",
    });
    expect(meta.twitter).toMatchObject({ card: "summary_large_image", title: "Tools · makhzan" });
    expect(meta.robots).toBeUndefined();
  });

  it("names the site's card unless the page has its own", () => {
    const image = (meta: ReturnType<typeof pageMetadata>) =>
      (meta.openGraph as { images?: { url: string }[] }).images?.[0]?.url;
    expect(image(pageMetadata({ title: "Shops" }))).toBe("/opengraph-image");
    // An explicit image would replace the segment's own opengraph-image.tsx.
    expect(image(pageMetadata({ title: "Tools", ownCard: true }))).toBeUndefined();
  });

  it("keeps search out of the index, but followed", () => {
    expect(pageMetadata({ title: "relay", noindex: true }).robots).toEqual({
      index: false,
      follow: true,
    });
  });
});

describe("homeJsonLd", () => {
  it("names the site and who runs it, on the site's own origin", () => {
    const [organization, website] = homeJsonLd("https://makhzan.example/");
    expect(organization).toMatchObject({
      "@context": "https://schema.org",
      "@type": "Organization",
      "@id": "https://makhzan.example/#organization",
      name: "makhzan",
      url: "https://makhzan.example/",
      logo: "https://makhzan.example/icon-512.png",
    });
    expect(website).toMatchObject({
      "@context": "https://schema.org",
      "@type": "WebSite",
      "@id": "https://makhzan.example/#website",
      name: "makhzan",
      url: "https://makhzan.example/",
      publisher: { "@id": "https://makhzan.example/#organization" },
    });
  });

  // Google retired the sitelinks search box (November 2024); the site has no
  // other name, so an alternateName would be invented.
  it("has no search action and no alternate name", () => {
    const text = JSON.stringify(homeJsonLd("https://makhzan.example/"));
    expect(text).not.toMatch(/SearchAction|potentialAction|alternateName/);
  });
});

describe("sitemapEntries", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("lists every page with something on it, on SITE_URL", () => {
    vi.stubEnv("SITE_URL", "https://makhzan.example");
    const urls = sitemapEntries(SEALS, [
      {
        slug: "shop-a",
        name: "Shop A",
        name_ar: null,
        website_url: null,
        listing_count: 10,
        in_stock_count: 5,
        last_verified_at: "2026-11-01T00:00:00Z",
        domains: [],
      },
      {
        slug: "gone",
        name: "Gone",
        name_ar: null,
        website_url: null,
        listing_count: 0,
        in_stock_count: 0,
        last_verified_at: null,
        domains: [],
      },
    ]).map((entry) => entry.url.replace("https://makhzan.example", ""));
    expect(urls).toEqual([
      "/",
      "/departments",
      "/departments/seals-bearings",
      "/departments/tools",
      "/departments/seals-bearings/seals",
      "/departments/seals-bearings/o-rings",
      "/departments/seals-bearings/oil-seals",
      "/departments/seals-bearings/bearings",
      "/departments/seals-bearings/other",
      "/departments/tools/calipers",
      "/shops",
      "/shops/shop-a",
      "/how-we-crawl",
      "/for-suppliers",
    ]);
  });
});

describe("clampText", () => {
  it("leaves a short title alone and cuts a long one at a word", () => {
    expect(clampText("ESP32 DevKit", 20)).toBe("ESP32 DevKit");
    expect(clampText("Caliper 300mm stainless with knife points and a case", 30)).toBe(
      "Caliper 300mm stainless with…",
    );
  });
});

describe("breadcrumbJsonLd", () => {
  it("lists the trail in order, links absolute, the page itself last and unlinked", () => {
    const data = breadcrumbJsonLd(
      [
        { label: "Electronics", href: "/departments/electronics" },
        { label: "Resistors", href: "/departments/electronics/resistors" },
      ],
      "1k Resistor",
    );
    expect(data["@type"]).toBe("BreadcrumbList");
    expect(data.itemListElement.map((i) => [i.position, i.name])).toEqual([
      [1, "Electronics"],
      [2, "Resistors"],
      [3, "1k Resistor"],
    ]);
    expect(data.itemListElement[0].item).toMatch(/^https?:\/\/.+\/departments\/electronics$/);
    expect(data.itemListElement[2]).not.toHaveProperty("item");
  });
});

describe("pagedPath", () => {
  it("keeps a positive offset and drops everything else", () => {
    expect(pagedPath("/departments/x", { offset: "24", sort: "price_asc" })).toBe("/departments/x?offset=24");
    expect(pagedPath("/departments/x", { sort: "price_asc", in_stock: "all" })).toBe("/departments/x");
    expect(pagedPath("/departments/x", { offset: "0" })).toBe("/departments/x");
    expect(pagedPath("/departments/x", { offset: "abc" })).toBe("/departments/x");
    expect(pagedPath("/departments/x", { offset: ["48", "72"] })).toBe("/departments/x?offset=48");
  });
});
