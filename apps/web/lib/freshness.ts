/**
 * How old a price is, and how loudly to say so (rules F1, F2).
 *
 * A large share of the catalogue is weeks or months old — two shops cannot be
 * reached from the crawler — so age is not an edge case to tuck away. It gets
 * louder as it grows: quiet up to two weeks (about one crawl cycle and a
 * margin), muted to six weeks, and a warning after that.
 */

export type FreshnessTier = "quiet" | "muted" | "warn";

const DAY = 86_400_000;

/**
 * Stale: last checked more than this many whole days ago. One line everywhere:
 * the warn tier of F2 ("Price may be out of date"), the shop note of F3, and
 * the filter that hides stale products and folds stale offers (C2b), so what a
 * page warns about and what the filter hides are the same thing.
 *
 * The API holds the same number in `makhzan_schemas/freshness.py` (its `fresh`
 * search filter); tests/freshness.test.tsx reads that file to keep them equal.
 */
export const STALE_AFTER_DAYS = 45;

/** Last day each tier covers. Over `MUTED_MAX` is a warning. */
export const QUIET_MAX_DAYS = 14;
export const MUTED_MAX_DAYS = STALE_AFTER_DAYS;

/** Whole days between a check and now. Never negative: a clock that runs a
 *  little ahead of the crawler's must not render "checked -1 days ago". */
export function daysSince(lastVerified: Date, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - lastVerified.getTime()) / DAY));
}

export function freshnessTier(lastVerified: Date, now: Date = new Date()): FreshnessTier {
  const days = daysSince(lastVerified, now);
  if (days <= QUIET_MAX_DAYS) return "quiet";
  if (days <= MUTED_MAX_DAYS) return "muted";
  return "warn";
}

/** Checked more than STALE_AFTER_DAYS ago (rule C2b). Unknown is not stale:
 *  there is no check to be old. */
export function isStaleCheck(lastVerified: Date | null, now: Date = new Date()): boolean {
  return lastVerified !== null && daysSince(lastVerified, now) > STALE_AFTER_DAYS;
}

/**
 * The API reports a check time two ways: the search index stores epoch
 * seconds, and product/listing payloads carry ISO strings. One parser, so no
 * call site guesses which it was handed.
 */
export function parseVerified(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return value;
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "today", "1 day ago", "12 days ago". */
export function agoText(days: number): string {
  if (days === 0) return "today";
  return days === 1 ? "1 day ago" : `${days} days ago`;
}
