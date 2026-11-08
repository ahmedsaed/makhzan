import type { MetadataRoute } from "next";

import { absoluteUrl } from "@/lib/site";

/**
 * Everything may be crawled except search, which is infinite query space:
 * every query and filter is another URL with nothing a department or category page
 * does not already list. Search pages also say `noindex` themselves, for any
 * crawler that arrives there anyway. `/api/` is the JSON the browser fetches,
 * not a page.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/search", "/api/"] },
    sitemap: absoluteUrl("/sitemap.xml"),
  };
}

/** SITE_URL is read when the file is requested, not baked in at build. */
export const dynamic = "force-dynamic";
