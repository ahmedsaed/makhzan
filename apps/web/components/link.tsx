import NextLink from "next/link";
import type { ComponentProps } from "react";

/**
 * `next/link` with prefetching off by default.
 *
 * Why this exists rather than `prefetch={false}` at each call site: a prefetch
 * is a full server render. Every page here is a list of links to other pages —
 * a search result page carries 24 product links, browse and supplier pages the
 * same — so Next's default (prefetch every link that scrolls into view) turns
 * one page view into ~30 server-rendered product pages, each of which fetches
 * the product and then its similar products. Measured on the live site: one
 * search for "arduino uno" fired 31 `?_rsc=` prefetch requests.
 *
 * The catalogue makes that permanent rather than incidental — the whole product
 * is a dense graph of links between products, suppliers and categories — so the
 * default is wrong for us everywhere, not on one page.
 *
 * In the App Router `prefetch={false}` disables prefetching on both viewport
 * and hover. The cost is that a click now waits for the navigation instead of
 * having it in hand; that is the intended exchange, and it is a per-click cost
 * paid only for pages someone actually opens.
 *
 * Pass `prefetch` explicitly to opt a specific link back in.
 */
export function Link({ prefetch = false, ...props }: ComponentProps<typeof NextLink>) {
  return <NextLink prefetch={prefetch} {...props} />;
}
