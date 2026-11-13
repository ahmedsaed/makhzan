import type { MetadataRoute } from "next";

import {
  titleOf,
  type Category,
  type ShopSummary,
  type SitemapPage,
  type SitemapProduct,
} from "@/lib/api";
import { routes } from "@/lib/routes";
import { listedShops } from "@/lib/shops";
import { absoluteUrl } from "@/lib/site";
import { totalOf, departmentsFrom } from "@/lib/departments";

/**
 * The sitemap's entries, from the taxonomy and the shop list.
 *
 * Only pages with something on them: a department or category with no products,
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
    changeFrequency: "daily" | "weekly" | "monthly" | "yearly",
    priority: number,
    lastModified?: string,
  ) => ({
    url: absoluteUrl(path),
    changeFrequency,
    priority,
    ...(lastModified && { lastModified }),
  });

  const departments = departmentsFrom(categories).filter((department) => department.count > 0);
  const withProducts = categories.filter((category) => totalOf(category.ref, categories) > 0);

  return [
    page(routes.home(), "daily", 1),
    page(routes.departments(), "weekly", 0.8),
    ...departments.map((department) => page(routes.department(department.domain), "weekly", 0.8)),
    ...withProducts.map((category) => page(routes.category(category.ref), "weekly", 0.7)),
    page(routes.shops(), "weekly", 0.6),
    ...listedShops(shops).map((shop) =>
      page(routes.shop(shop.slug), "weekly", 0.6, shop.last_verified_at ?? undefined),
    ),
    page(routes.howWeCrawl(), "monthly", 0.3),
    page(routes.forSuppliers(), "monthly", 0.3),
    page(routes.privacy(), "yearly", 0.1),
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

/**
 * A product's sitemap entry: its readable URL, when its content changed, and
 * its main photo as an `<image:image>`.
 *
 * The photo follows Google's image sitemap guidance
 * (developers.google.com/search/docs/crawling-indexing/sitemaps/image-sitemaps):
 * `image:loc` may be on another host, as every product photo is (they are the
 * shops' own, hotlinked, decision 0003). Only an absolute http(s) URL is
 * listed. Next writes the URL into the XML as given, unescaped, so it is
 * escaped here: a shop's photo URL with `&` in its query would otherwise make
 * the whole file invalid XML.
 */
export function productEntries(products: SitemapProduct[]): MetadataRoute.Sitemap {
  return products.map((product) => ({
    // The same slug the product page builds, so the listed URL is the one it
    // answers 200 on rather than one it redirects.
    url: absoluteUrl(
      routes.product(
        product.id,
        titleOf({ title_en: product.title_en, title_ar: product.title_ar ?? null }) ||
          product.part_number,
      ),
    ),
    lastModified: product.changed_at,
    // `href` percent-encodes what a URL may not hold raw (spaces, Arabic file
    // names), as a sitemap's URLs must be; escapeXml then makes it XML.
    ...(isWebUrl(product.image) && { images: [escapeXml(new URL(product.image).href)] }),
  }));
}

function isWebUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    const { protocol } = new URL(url);
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
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
