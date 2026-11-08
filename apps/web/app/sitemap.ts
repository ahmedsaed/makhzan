import type { MetadataRoute } from "next";

import { fetchCategories, fetchSitemapProducts, fetchSuppliers } from "@/lib/api";
import {
  countProducts,
  productChunk,
  productEntries,
  sitemapEntries,
  sitemapIds,
} from "@/lib/sitemap";

/**
 * The sitemap, as numbered files under /sitemap/{id}.xml, listed by the index
 * at /sitemap.xml (app/sitemap-index.xml/route.ts, by a rewrite), which is what
 * robots.txt names.
 *
 * 0 is every browsable page: home, the trades and each trade and category, the
 * shops and each shop, and the two pages for suppliers. 1..N are the products,
 * 50,000 to a file, read from the API's keyset listing by id, each with the
 * date its visible content last changed (not its last recheck: Google ignores
 * a lastmod that is not consistently accurate).
 *
 * Fails soft: with the API down there is only file 0, and it still lists the
 * static pages. A product file whose read fails is an error rather than an
 * empty list, so a crawler retries it instead of seeing every product gone.
 */
export async function generateSitemaps() {
  return sitemapIds(await countProducts(fetchSitemapProducts));
}

export default async function sitemap(props: {
  id: Promise<string>;
}): Promise<MetadataRoute.Sitemap> {
  const id = Number(await props.id);
  if (id > 0) return productEntries(await productChunk(id, fetchSitemapProducts));

  const [categories, shops] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchSuppliers().catch(() => []),
  ]);
  return sitemapEntries(categories, shops);
}

/** Read per request: the URLs are on SITE_URL, which a build does not have,
 *  and the taxonomy and shop list behind it are cached by lib/api.ts anyway.
 *  A product file is one 50,000-row read of an indexed table, and crawlers
 *  fetch sitemaps seldom: not worth a cache that would need SITE_URL at build. */
export const dynamic = "force-dynamic";
