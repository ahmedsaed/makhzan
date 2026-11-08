import type { MetadataRoute } from "next";

import type { Category, ShopSummary, SitemapPage, SitemapProduct } from "@/lib/api";
import { routes } from "@/lib/routes";
import { listedShops } from "@/lib/shops";
import { absoluteUrl } from "@/lib/site";
import { totalOf, tradesFrom } from "@/lib/trades";

/**
 * The sitemap's entries, from the taxonomy and the shop list.
 *
 * Only pages with something on them: a trade or category with no products,
 * or a shop with no active listings, is left out, as the site's own lists
 * leave them out.
 *
 * This is sitemap 0. Products are sitemaps 1..N, below.
 */
export function sitemapEntries(
  categories: Category[],
  shops: ShopSummary[],
): MetadataRoute.Sitemap {
  const page = (
    path: string,
    changeFrequency: "daily" | "weekly" | "monthly",
    priority: number,
    lastModified?: string,
  ) => ({
    url: absoluteUrl(path),
    changeFrequency,
    priority,
    ...(lastModified && { lastModified }),
  });

  const trades = tradesFrom(categories).filter((trade) => trade.count > 0);
  const withProducts = categories.filter((category) => totalOf(category.ref, categories) > 0);

  return [
    page(routes.home(), "daily", 1),
    page(routes.trades(), "weekly", 0.8),
    ...trades.map((trade) => page(routes.trade(trade.domain), "weekly", 0.8)),
    ...withProducts.map((category) => page(routes.category(category.ref), "weekly", 0.7)),
    page(routes.shops(), "weekly", 0.6),
    ...listedShops(shops).map((shop) =>
      page(routes.shop(shop.slug), "weekly", 0.6, shop.last_verified_at ?? undefined),
    ),
    page(routes.howWeCrawl(), "monthly", 0.3),
    page(routes.forSuppliers(), "monthly", 0.3),
  ];
}

// --------------------------------------------------------------------------- //
// Products: sitemaps 1..N, 50,000 to a file
// --------------------------------------------------------------------------- //

/** The most URLs one sitemap file may hold (sitemaps.org, and Google). */
export const PRODUCTS_PER_SITEMAP = 50_000;

/** Reads one page of `GET /sitemap/products`. */
export type SitemapFetcher = (after: string | null, limit: number) => Promise<SitemapPage>;

/**
 * The sitemap ids: 0 for the pages above, then one per 50,000 products. Only
 * 0 when the count is unknown (the API is down), so the pages are still
 * listed and no product file is promised that could not be built.
 */
export function sitemapIds(totalProducts: number | null): { id: number }[] {
  const chunks = Math.ceil(Math.max(0, totalProducts ?? 0) / PRODUCTS_PER_SITEMAP);
  return Array.from({ length: chunks + 1 }, (_, id) => ({ id }));
}

/** How many products there are, from the endpoint's first page; null when
 *  the API cannot say. */
export async function countProducts(fetchPage: SitemapFetcher): Promise<number | null> {
  try {
    return (await fetchPage(null, 1)).total ?? null;
  } catch {
    return null;
  }
}

/**
 * The products in sitemap `id` (1-based): the id-th page of 50,000.
 *
 * Keyset paging cannot jump, so file k reads the k-1 pages before it for
 * their cursors. At today's ~60k products that is one extra read for file 2;
 * if the catalogue grows far past that, have the API return each chunk's
 * first id with the count instead.
 */
export async function productChunk(
  id: number,
  fetchPage: SitemapFetcher,
): Promise<SitemapProduct[]> {
  let after: string | null = null;
  for (let chunk = 1; chunk <= id; chunk++) {
    const page = await fetchPage(after, PRODUCTS_PER_SITEMAP);
    if (chunk === id) return page.items;
    if (!page.next) return [];
    after = page.next;
  }
  return [];
}

/** A product's sitemap entry: its readable URL, and when its content changed. */
export function productEntries(products: SitemapProduct[]): MetadataRoute.Sitemap {
  return products.map((product) => ({
    url: absoluteUrl(routes.product(product.id, product.title_en)),
    lastModified: product.changed_at,
  }));
}

/** The URL Next serves sitemap `id` at (`generateSitemaps`: /sitemap/{id}.xml). */
export function sitemapUrl(id: number): string {
  return absoluteUrl(`/sitemap/${id}.xml`);
}

/**
 * The sitemap index, served at /sitemap.xml: `generateSitemaps` serves only
 * the numbered files, so the one address robots.txt names is built here.
 */
export function sitemapIndexXml(ids: { id: number }[]): string {
  const entries = ids
    .map(({ id }) => `<sitemap><loc>${escapeXml(sitemapUrl(id))}</loc></sitemap>`)
    .join("\n");
  return (
    '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
    `${entries}\n` +
    "</sitemapindex>\n"
  );
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
