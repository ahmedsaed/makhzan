import { robotsTxt } from "@/lib/robots";
import { absoluteUrl } from "@/lib/site";

/**
 * robots.txt, hand-written because Next's `MetadataRoute.Robots` cannot emit
 * the `Content-Signal` line. The policy (13 November 2026) and each group's
 * purpose are in lib/robots.ts. This is the only robots route: an
 * app/robots.ts beside it would claim the same path.
 */
export function GET() {
  return new Response(robotsTxt(absoluteUrl("/sitemap.xml")), {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600",
    },
  });
}

/** SITE_URL is read when the file is requested, not baked in at build. */
export const dynamic = "force-dynamic";
