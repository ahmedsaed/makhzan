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

// --------------------------------------------------------------------------- //
// What is inside a trade, and how its tree is browsed
// --------------------------------------------------------------------------- //

/** A trade as the home and all-trades pages list it: its name, its size, and
 *  what is inside it, in words. */
export type TradeSummary = Trade & { inside: string[] };

/** Leaves hold the products; parents are browse groups. */
export function leavesOf(categories: Category[]): Category[] {
  const parents = new Set(categories.map((category) => category.parent));
  return categories.filter((category) => !parents.has(category.ref));
}

/**
 * Counts are per category, not per subtree: a group's own count is what is
 * filed on it directly, usually nothing. This is the subtree's total.
 */
export function totalOf(ref: string, categories: Category[]): number {
  const own = categories.find((category) => category.ref === ref)?.count ?? 0;
  return categories
    .filter((category) => category.parent === ref)
    .reduce((sum, child) => sum + totalOf(child.ref, categories), own);
}

/**
 * "Resistors, batteries, connectors, ICs": the names read as one phrase, so
 * only the first keeps its capital. A word is lowered only when it is plainly
 * an ordinary capitalised word; "PLCs", "3D", "O-Rings" and "PTFE" keep theirs.
 */
export function asPhrase(names: string[]): string {
  return names
    .map((name, index) =>
      index === 0
        ? name
        : name
            .split(" ")
            .map((word) => (/^[A-Z][a-z]+$/.test(word) ? word.toLowerCase() : word))
            .join(" "),
    )
    .join(", ");
}

/**
 * A trade's biggest categories, which say what is inside far better than its
 * name does ("Seals & Bearings": O-rings, bearings, oil seals). "Other …"
 * buckets are skipped: they are the one thing a name cannot describe.
 */
export function insideOf(domain: string, categories: Category[], limit = 4): string[] {
  return leavesOf(categories.filter((category) => category.domain === domain))
    .filter((category) => category.count > 0 && !/^other\b/i.test(category.name_en))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
    .map((category) => category.name_en);
}

/** Every trade that has products, with what is inside, largest first. */
export function tradeSummaries(categories: Category[], limit = 4): TradeSummary[] {
  return tradesFrom(categories)
    .filter((trade) => trade.count > 0)
    .map((trade) => ({
      ...trade,
      inside: insideOf(trade.domain, categories, limit),
    }));
}

export type TradeNode = Category & { total: number };

/**
 * One trade's tree as its page shows it: the top-level groups, the selected
 * group and its categories, and — when nothing is selected — the trade's
 * biggest categories. Empty branches are left out: a tile that leads to
 * nothing is a dead end.
 *
 * `selected` is the category the page is narrowed to; its group is the
 * top-level category above it, or itself when it is top level.
 */
export function tradeTree(categories: Category[], selected: string | null = null) {
  const withTotals = (list: Category[]): TradeNode[] =>
    list
      .map((category) => ({
        ...category,
        total: totalOf(category.ref, categories),
      }))
      .filter((node) => node.total > 0)
      .sort((a, b) => b.total - a.total);

  const byRef = new Map(categories.map((category) => [category.ref, category]));
  let root = selected ? byRef.get(selected) : undefined;
  while (root?.parent && byRef.has(root.parent)) root = byRef.get(root.parent);

  const groups = withTotals(categories.filter((category) => !category.parent));
  const group = root ? (groups.find((node) => node.ref === root.ref) ?? null) : null;
  const children = group ? withTotals(categories.filter((c) => c.parent === group.ref)) : [];
  // A flat trade has nothing to add here: its groups already are its categories.
  const nested = groups.some((node) => categories.some((c) => c.parent === node.ref));
  const top = !group && nested ? withTotals(leavesOf(categories)).slice(0, 8) : [];

  return { groups, group, children, top };
}
