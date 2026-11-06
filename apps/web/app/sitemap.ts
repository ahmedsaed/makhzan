import type { MetadataRoute } from "next";

import { fetchCategories, fetchSuppliers } from "@/lib/api";
import { sitemapEntries } from "@/lib/sitemap";

/**
 * Every browsable page: home, the trades and each trade and category, the
 * shops and each shop, and the two pages for suppliers.
 *
 * Products are not listed yet. The API has no cheap way to enumerate their
 * ids (search pages at most 100 hits per request and stops at 50,000), and
 * the trade and category pages already link to every product a crawler can
 * reach. A product sitemap needs a keyset-paged id listing from the API; see
 * lib/sitemap.ts.
 *
 * Fails soft: with the API down, the static pages are still listed.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [categories, shops] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchSuppliers().catch(() => []),
  ]);
  return sitemapEntries(categories, shops);
}

/** Read per request: the URLs are on SITE_URL, which a build does not have,
 *  and the taxonomy and shop list behind it are cached by lib/api.ts anyway. */
export const dynamic = "force-dynamic";
