import type { MetadataRoute } from "next";

import { absoluteUrl } from "@/lib/site";

/**
 * SEO backlink crawlers, refused the whole site. They build link indexes to
 * sell to marketers; a directory gains nothing from them, and in November 2026
 * these two alone were about 30% of the site's traffic (proxy logs, 11 Nov).
 * Each token is the one its operator documents for robots.txt. A crawler that
 * matches a named group ignores the `*` group, so each needs its own entry.
 * AI and search crawlers are deliberately left under `*`.
 */
const REFUSED_CRAWLERS = ["SemrushBot", "SERankingBacklinksBot"];

/**
 * Everything else may crawl everything except search, which is infinite query
 * space: every query and filter is another URL with nothing a department or
 * category page does not already list. Search pages also say `noindex`
 * themselves, for any crawler that arrives there anyway. `/api/` is the JSON
 * the browser fetches, not a page.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      { userAgent: "*", allow: "/", disallow: ["/search", "/api/"] },
      ...REFUSED_CRAWLERS.map((userAgent) => ({ userAgent, disallow: "/" })),
    ],
    sitemap: absoluteUrl("/sitemap.xml"),
  };
}

/** SITE_URL is read when the file is requested, not baked in at build. */
export const dynamic = "force-dynamic";
