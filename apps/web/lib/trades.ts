import type { Category } from "@/lib/api";

/**
 * Trades are what the backend calls domains. The API has no /domains endpoint —
 * a trade exists because categories belong to it — so names are derived from
 * the slug and sizes from the categories' counts.
 */

export type Trade = { domain: string; label: string; count: number };

/** "seals-bearings" → "Seals & Bearings". */
export function tradeLabel(domain: string): string {
  return domain
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" & ");
}

/** Roll the flat category payload up into trades, largest first. */
export function tradesFrom(categories: Category[]): Trade[] {
  const totals = new Map<string, number>();
  for (const category of categories) {
    totals.set(category.domain, (totals.get(category.domain) ?? 0) + category.count);
  }
  return [...totals.entries()]
    .map(([domain, count]) => ({ domain, label: tradeLabel(domain), count }))
    .sort((a, b) => b.count - a.count);
}
