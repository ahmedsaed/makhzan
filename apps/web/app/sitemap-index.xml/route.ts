import { fetchSitemapProducts } from "@/lib/api";
import { countProducts, sitemapIds, sitemapIndexXml } from "@/lib/sitemap";

/**
 * The sitemap index, served at /sitemap.xml (a rewrite in next.config.ts):
 * the one address robots.txt names, listing the numbered files app/sitemap.ts
 * serves. Next's `generateSitemaps` serves only /sitemap/{id}.xml and no
 * index, and a route at app/sitemap.xml/ conflicts with it at build, so the
 * index lives here and is built from the same count.
 *
 * Fails soft like the files: with the API down it lists file 0 alone.
 */
export async function GET() {
  const ids = sitemapIds(await countProducts(fetchSitemapProducts));
  return new Response(sitemapIndexXml(ids), {
    headers: { "content-type": "application/xml" },
  });
}

/** SITE_URL is read per request, as for the files themselves. */
export const dynamic = "force-dynamic";
