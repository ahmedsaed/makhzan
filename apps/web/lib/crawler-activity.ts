/**
 * The crawler's public record as words: for the "Crawler activity" section of
 * /how-we-crawl and the one line on each shop's page.
 *
 * Shop owners read these against their own server logs, so the wording is
 * calm and exact: times are relative with the absolute time beside them, a gap
 * is floored to the second (never rounded up into a promise we did not keep),
 * an unmeasured figure is "—", and "Paused" is never given a reason.
 */
import type { ShopCrawlActivity } from "@/lib/api";
import { formatCount, plural } from "@/lib/format";

export const NOT_MEASURED = "—";

export const STATUS_LABEL: Record<ShopCrawlActivity["status"], string> = {
  active: "Active",
  paused: "Paused",
};

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function unit(count: number, name: string): string {
  return `${count} ${name}${count === 1 ? "" : "s"}`;
}

/** "3 hours ago", "in 5 hours", "just now". Whole units, rounded down. */
export function relativeTime(when: Date, now: Date = new Date()): string {
  const diff = now.getTime() - when.getTime();
  const span = Math.abs(diff);
  let amount: string;
  if (span < MINUTE) return "just now";
  if (span < HOUR) amount = unit(Math.floor(span / MINUTE), "minute");
  else if (span < DAY) amount = unit(Math.floor(span / HOUR), "hour");
  else amount = unit(Math.floor(span / DAY), "day");
  return diff >= 0 ? `${amount} ago` : `in ${amount}`;
}

const UTC_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** "9 Nov 2026, 03:00 UTC": the tooltip under every relative time. In UTC so the
 *  server and every reader agree, whatever their own zone. */
export function absoluteTime(when: Date): string {
  return `${UTC_TIME.format(when)} UTC`;
}

/** "15 s", "2 min", or "—" when nothing was measured. Floored. */
export function formatGap(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return NOT_MEASURED;
  if (seconds >= 120) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds)} s`;
}

/** "412", or "at least 412" when some run in the window did not record its
 *  count — and "—" when none did, rather than "at least 0". */
export function formatRequests(count: number, partial: boolean): string {
  if (!partial) return formatCount(count);
  return count > 0 ? `at least ${formatCount(count)}` : NOT_MEASURED;
}

/** "03:00 UTC". */
export function refreshTime(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00 UTC`;
}

export function parseTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * The parts of a shop page's line, before the "How we crawl" link:
 * ["makhzan read this site 3 hours ago", "412 requests in the last 7 days",
 * "at least 15 s apart"]. A paused shop gets one sentence and no figures.
 */
export function shopActivityLine(
  shop: ShopCrawlActivity,
  windowDays: number,
  now: Date = new Date(),
): string[] {
  if (shop.status === "paused") return ["makhzan is not reading this site at the moment."];
  const lastRead = parseTime(shop.last_read_at);
  if (!lastRead) return ["makhzan has not read this site yet."];

  const parts = [`makhzan read this site ${relativeTime(lastRead, now)}`];
  if (shop.requests_7d > 0) {
    const requests = plural(shop.requests_7d, "request");
    parts.push(
      `${shop.requests_7d_partial ? "at least " : ""}${requests} in the last ${windowDays} days`,
    );
  }
  if (shop.requests_7d > 1 && shop.min_gap_s !== null) {
    parts.push(`at least ${formatGap(shop.min_gap_s)} apart`);
  }
  return parts;
}
