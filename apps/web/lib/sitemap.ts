import type { MetadataRoute } from "next";

import type { Category, ShopSummary } from "@/lib/api";
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
 * Products would need an API endpoint that lists ids cheaply, keyset-paged
 * (`GET /products/ids?after=<id>&limit=50000`, returning id and last check),
 * one sitemap per 50,000 via `generateSitemaps`. Search cannot do it: it
 * pages 100 at a time and stops at 50,000 hits.
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
