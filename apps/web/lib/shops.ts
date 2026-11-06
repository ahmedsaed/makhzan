import type { Listing, SearchHit, ShopSummary } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { freshnessTier, parseVerified } from "@/lib/freshness";
import { tradeLabel } from "@/lib/trades";

/**
 * What the shop pages say about a shop, kept out of the components so the
 * rules behind it — when a shop counts as stale, which shops are listed at all —
 * are tested rather than read off markup.
 */

/**
 * Shops worth listing. `/suppliers` returns every shop, including one with no
 * active listings left; a row reading "0 products" sends a visitor nowhere.
 */
export function listedShops<T extends { listing_count: number }>(shops: T[]): T[] {
  return shops.filter((shop) => shop.listing_count > 0);
}

/**
 * A shop whose newest check is in the warning tier (over 45 days, rule F2).
 * Its listings all carry the warning individually; the shop's own page has to
 * say why, in plain words (F3).
 *
 * A shop never checked at all is not stale — it has nothing to be stale about.
 */
export function isStale(lastVerified: string | null, now: Date = new Date()): boolean {
  const date = parseVerified(lastVerified);
  return date !== null && freshnessTier(date, now) === "warn";
}

/** "shop-a.test", for "Visit shop-a.test". The `www.` is noise in a button. */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const DAY_MONTH = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "Africa/Cairo",
});
const DAY_MONTH_YEAR = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "Africa/Cairo",
});

/** "23 Aug", or "23 Aug 2025" once it is not this year's. */
export function formatDay(date: Date, now: Date = new Date()): string {
  const sameYear = date.getUTCFullYear() === now.getUTCFullYear();
  return (sameYear ? DAY_MONTH : DAY_MONTH_YEAR).format(date);
}

/** "Electronics", "Electronics and Tools", "Electronics, Tools and Chemicals". */
export function tradesInWords(domains: ShopSummary["domains"], limit = 3): string {
  const names = domains.slice(0, limit).map((d) => tradeLabel(d.domain));
  const rest = domains.length - names.length;
  if (rest > 0) names.push(rest === 1 ? "1 more trade" : `${rest} more trades`);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

export type TradeShare = {
  domain: string | null;
  label: string;
  count: number;
  percent: number;
};

/**
 * A shop's catalogue by trade, for the bar on its page: the largest few, then
 * everything else folded into one segment so a shop spread over many trades
 * still draws a readable bar. `domain` is null for that fold.
 */
export function tradeShares(domains: ShopSummary["domains"], segments = 3): TradeShare[] {
  const total = domains.reduce((sum, d) => sum + d.count, 0);
  if (total === 0) return [];
  const share = (count: number) => (count / total) * 100;
  const head = domains.length > segments + 1 ? domains.slice(0, segments) : domains;
  const out: TradeShare[] = head.map((d) => ({
    domain: d.domain,
    label: `${tradeLabel(d.domain)} ${formatCount(d.count)}`,
    count: d.count,
    percent: share(d.count),
  }));
  const tail = domains.slice(head.length);
  if (tail.length > 0) {
    const count = tail.reduce((sum, d) => sum + d.count, 0);
    out.push({
      domain: null,
      label: `${tail.length} other trades ${formatCount(count)}`,
      count,
      percent: share(count),
    });
  }
  return out;
}

/**
 * Search within one shop. The search page owns `/search`; this only builds the
 * address, so a shop's category links and its search field agree on it.
 */
export function shopSearchUrl(
  slug: string,
  { category, domain }: { category?: string; domain?: string } = {},
): string {
  const params = new URLSearchParams({ shop: slug });
  if (domain) params.set("domain", domain);
  if (category) params.set("category", category);
  return `/search?${params.toString()}`;
}

/**
 * One of the shop's listings in the shape of a search hit, so it renders
 * through ResultList and carries the same facts as every other result (C1).
 *
 * Null for a listing the grouping step left without a product: a result must
 * open a product page (P1), and that one has none.
 */
export function hitFromListing(listing: Listing): SearchHit | null {
  if (!listing.product_id) return null;
  const verified = parseVerified(listing.last_verified_at);
  return {
    id: listing.product_id,
    domain: listing.category?.domain ?? "",
    part_number: listing.part_number,
    title_en: listing.title_en,
    title_ar: listing.title_ar,
    brand: listing.brand,
    category_slug: listing.category?.slug ?? null,
    category_ref: listing.category?.ref ?? null,
    category_name: listing.category?.name_en ?? null,
    supplier_name: listing.supplier?.name ?? null,
    // This shop's offer, so this shop's name: the row is about what it sells.
    supplier_count: 1,
    offer_count: 1,
    min_price: listing.price,
    max_price: listing.price,
    currency: listing.currency,
    in_stock: listing.stock_signal === "in_stock" || listing.stock_signal === "low_stock",
    image: listing.images[0] ?? null,
    // The index stores epoch seconds; match it.
    last_verified_at: verified ? Math.floor(verified.getTime() / 1000) : null,
  };
}
