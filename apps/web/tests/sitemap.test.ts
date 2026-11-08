import { afterEach, describe, expect, it, vi } from "vitest";

import type { SitemapPage, SitemapProduct } from "@/lib/api";
import {
  PRODUCTS_PER_SITEMAP,
  countProducts,
  productChunk,
  productEntries,
  sitemapIds,
  sitemapIndexXml,
  type SitemapFetcher,
} from "@/lib/sitemap";

/** A fake `GET /sitemap/products` over `total` products whose ids sort in order. */
function catalogue(total: number) {
  const ids = Array.from({ length: total }, (_, i) => `p${String(i).padStart(7, "0")}`);
  const calls: (string | null)[] = [];
  const fetchPage: SitemapFetcher = async (after, limit) => {
    calls.push(after);
    const start = after === null ? 0 : ids.indexOf(after) + 1;
    const slice = ids.slice(start, start + limit);
    const page: SitemapPage = {
      items: slice.map((id) => ({ id, title_en: null, changed_at: "2026-11-01T00:00:00Z" })),
      next: slice.length === limit ? slice[slice.length - 1] : null,
      total: after === null ? total : null,
    };
    return page;
  };
  return { ids, calls, fetchPage };
}

describe("sitemapIds", () => {
  it("is file 0 alone without products, or when the count is unknown", () => {
    expect(sitemapIds(0)).toEqual([{ id: 0 }]);
    expect(sitemapIds(null)).toEqual([{ id: 0 }]);
  });

  it("adds one file per 50,000 products, rounding up", () => {
    expect(sitemapIds(1)).toEqual([{ id: 0 }, { id: 1 }]);
    expect(sitemapIds(PRODUCTS_PER_SITEMAP)).toEqual([{ id: 0 }, { id: 1 }]);
    expect(sitemapIds(PRODUCTS_PER_SITEMAP + 1)).toEqual([{ id: 0 }, { id: 1 }, { id: 2 }]);
    expect(sitemapIds(60_500).map(({ id }) => id)).toEqual([0, 1, 2]);
  });
});

describe("countProducts", () => {
  it("reads the total from a one-row first page", async () => {
    const { fetchPage } = catalogue(7);
    const spy = vi.fn(fetchPage);
    expect(await countProducts(spy)).toBe(7);
    expect(spy).toHaveBeenCalledWith(null, 1);
  });

  it("is null when the API is down, so the pages are still listed", async () => {
    expect(await countProducts(async () => Promise.reject(new Error("down")))).toBeNull();
  });
});

describe("productChunk", () => {
  const total = 2 * PRODUCTS_PER_SITEMAP + 3;

  it("splits the catalogue into files of 50,000, every product exactly once", async () => {
    const { ids, fetchPage } = catalogue(total);
    const files = await Promise.all([1, 2, 3].map((id) => productChunk(id, fetchPage)));
    expect(files.map((items) => items.length)).toEqual([
      PRODUCTS_PER_SITEMAP,
      PRODUCTS_PER_SITEMAP,
      3,
    ]);
    expect(files.flat().map((item) => item.id)).toEqual(ids);
  });

  it("walks the cursors of the files before it", async () => {
    const { ids, calls, fetchPage } = catalogue(total);
    await productChunk(3, fetchPage);
    expect(calls).toEqual([null, ids[PRODUCTS_PER_SITEMAP - 1], ids[2 * PRODUCTS_PER_SITEMAP - 1]]);
  });

  it("is empty past the end of the catalogue", async () => {
    const { fetchPage } = catalogue(3);
    expect(await productChunk(2, fetchPage)).toEqual([]);
  });
});

describe("productEntries", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("uses the readable product URL and the content-change date", () => {
    vi.stubEnv("SITE_URL", "https://makhzan.example");
    const products: SitemapProduct[] = [
      {
        id: "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
        title_en: "SG90 Micro Servo",
        changed_at: "2026-10-02T08:30:00Z",
      },
      {
        id: "6ec0bd7f-11c0-43da-975e-2a8ad9ebae0b",
        title_en: null,
        changed_at: "2026-09-01T00:00:00Z",
      },
    ];
    expect(productEntries(products)).toEqual([
      {
        url: "https://makhzan.example/products/1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed-sg90-micro-servo",
        lastModified: "2026-10-02T08:30:00Z",
      },
      {
        url: "https://makhzan.example/products/6ec0bd7f-11c0-43da-975e-2a8ad9ebae0b",
        lastModified: "2026-09-01T00:00:00Z",
      },
    ]);
  });

  // The page slugs from titleOf(product) || part_number; the sitemap must
  // list that same URL, or Google is handed one that redirects.
  it("slugs as the product page does: the Arabic title's Latin words, then the part number", () => {
    vi.stubEnv("SITE_URL", "https://makhzan.example");
    const id = "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed";
    const [arabic, partOnly] = productEntries([
      { id, title_en: null, title_ar: "معجون لحام Soldering Paste", changed_at: "2026-10-02" },
      { id, title_en: null, title_ar: null, part_number: "LM7805", changed_at: "2026-10-02" },
    ]);
    expect(arabic.url).toBe(`https://makhzan.example/products/${id}-soldering-paste`);
    expect(partOnly.url).toBe(`https://makhzan.example/products/${id}-lm7805`);
  });
});

describe("sitemapIndexXml", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("lists each numbered file on SITE_URL", () => {
    vi.stubEnv("SITE_URL", "https://makhzan.example");
    const xml = sitemapIndexXml(sitemapIds(60_000));
    expect(xml).toContain('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">');
    expect(xml.match(/<loc>[^<]*<\/loc>/g)).toEqual([
      "<loc>https://makhzan.example/sitemap/0.xml</loc>",
      "<loc>https://makhzan.example/sitemap/1.xml</loc>",
      "<loc>https://makhzan.example/sitemap/2.xml</loc>",
    ]);
  });
});
