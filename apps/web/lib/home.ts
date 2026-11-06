import type { Category } from "@/lib/api";
import { leavesOf, tradesFrom, type Trade } from "@/lib/trades";

/**
 * What the home page shows a visitor who has not searched yet, worked out from
 * the API's own payloads so it is tested rather than read off markup.
 */

/**
 * Example searches under the home field: one per kind of buyer, spread across
 * the big trades so the row itself says what is in the catalogue.
 *
 * Hand-picked, not "popular": makhzan records no searches, so it has no
 * popularity to report. Each was checked against the live catalogue
 * (November 2026, in-stock results): ESP32 109, Arduino 427, relay module 340,
 * multimeter 180, digital caliper 489, drill bit 532, O-ring 3,056, oil seal
 * 1,065, contactor 1,010, PLA filament 87. Swap one out when it stops
 * returning a page of results.
 */
export const EXAMPLE_SEARCHES = [
  "ESP32",
  "Arduino",
  "relay module",
  "multimeter",
  "digital caliper",
  "drill bit",
  "O-ring",
  "oil seal",
  "contactor",
  "PLA filament",
] as const;

/** `/search?q=…` for an example: the same URL the field would submit. */
export function exampleHref(query: string): string {
  return `/search?${new URLSearchParams({ q: query })}`;
}

export type CategoryLink = { ref: string; name: string; count: number };

/** A trade on the home page: its size and its biggest categories as links. */
export type TradeCard = Trade & { categories: CategoryLink[] };

/**
 * Trades largest first, each with its biggest leaf categories. Leaves, because
 * they hold the products and name concrete things ("O-Rings", not "Seals &
 * Gaskets"); "Other …" buckets are skipped, as they are on every trade list,
 * because they are the one thing a name cannot describe.
 */
export function tradeCards(categories: Category[], perTrade = 4): TradeCard[] {
  return tradesFrom(categories)
    .filter((trade) => trade.count > 0)
    .map((trade) => ({
      ...trade,
      categories: leavesOf(categories.filter((category) => category.domain === trade.domain))
        .filter((category) => category.count > 0 && !/^other\b/i.test(category.name_en))
        .sort((a, b) => b.count - a.count)
        .slice(0, perTrade)
        .map((category) => ({
          ref: category.ref,
          name: category.name_en,
          count: category.count,
        })),
    }));
}
