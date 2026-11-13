/**
 * The crawler's public record as words: for the "Crawler activity" section of
 * /how-we-crawl and the one line on each shop's page.
 *
 * Shop owners read these against their own server logs, so the wording is
 * calm and exact: times are relative with the absolute time beside them, a gap
 * is floored to the second (never rounded up into a promise we did not keep),
 * an unmeasured figure is "—", and "Paused" is never given a reason.
 */
import type { GapBucket, ShopCrawlActivity } from "@/lib/api";
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

/** "makhzanbot · signed", "makhzanbot" or "browser User-Agent"; null when the
 *  latest run did not record who it said it was. */
export function identityLabel(identity: ShopCrawlActivity["identity"] | undefined): string | null {
  if (!identity) return null;
  if (identity.name === "makhzanbot") return identity.signed ? "makhzanbot · signed" : "makhzanbot";
  return "browser User-Agent";
}

/** "6 days", "1 day", "under a day", or null before any full pass completed.
 *  Rounded to the nearest day: the API gives tenths. */
export function formatCycleDays(days: number | null | undefined): string | null {
  if (days === null || days === undefined || !Number.isFinite(days) || days < 0) return null;
  if (days < 1) return "under a day";
  return unit(Math.round(days), "day");
}

const DAY_LABEL = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "numeric",
  month: "short",
});

/** "9 Nov" for an API date ("2026-11-09"), read as the UTC day it names. */
export function dayLabel(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? date : DAY_LABEL.format(parsed);
}

export type Sparkline = {
  /** Runs of consecutive recorded days, each as SVG points ("x,y x,y"). A day
   *  with no recorded count breaks the line: it is left out, never drawn as 0. */
  segments: string[];
  /** Recorded days that stand alone (no recorded neighbour), drawn as dots. */
  dots: [number, number][];
  /** The latest recorded day, marked. */
  last: [number, number];
  /** Every day in words, for the accessible name. */
  label: string;
};

/**
 * A shop's requests per day as a small line, or null when there is nothing
 * worth drawing (no day with a recorded count above zero: the count beside it
 * already says 0, or "—").
 */
export function sparkline(
  days: ShopCrawlActivity["requests_by_day"] | undefined,
  width = 56,
  height = 18,
): Sparkline | null {
  if (!days || days.length === 0) return null;
  const known = days.map((d) => d.requests).filter((n): n is number => n !== null);
  const max = Math.max(0, ...known);
  if (max <= 0) return null;
  const pad = 2;
  const step = days.length > 1 ? (width - 2 * pad) / (days.length - 1) : 0;
  const at = (i: number, n: number): [number, number] => [
    Number((pad + i * step).toFixed(1)),
    Number((height - pad - (n / max) * (height - 2 * pad)).toFixed(1)),
  ];

  const runs: [number, number][][] = [];
  let current: [number, number][] = [];
  days.forEach((day, i) => {
    if (day.requests === null) {
      if (current.length) runs.push(current);
      current = [];
    } else {
      current.push(at(i, day.requests));
    }
  });
  if (current.length) runs.push(current);

  const segments = runs
    .filter((run) => run.length > 1)
    .map((run) => run.map((point) => point.join(",")).join(" "));
  const dots = runs.filter((run) => run.length === 1).map((run) => run[0]);
  const lastRun = runs[runs.length - 1];
  const words = days
    .map(
      (d) =>
        `${dayLabel(d.date)}: ${d.requests === null ? "not recorded" : formatCount(d.requests)}`,
    )
    .join(", ");
  return {
    segments,
    dots,
    last: lastRun[lastRun.length - 1],
    label: `Requests per day, last ${days.length} days. ${words}`,
  };
}

export type GapRow = { label: string; count: number; percent: string; width: number };

/** "under 15 s", "15 s", "18–19 s", "60 s or more". */
export function gapBucketLabel(bucket: GapBucket): string {
  if (bucket.max_s === null) return `${bucket.min_s} s or more`;
  if (bucket.min_s === 0) return `under ${bucket.max_s + 1} s`;
  if (bucket.min_s === bucket.max_s) return `${bucket.min_s} s`;
  return `${bucket.min_s}–${bucket.max_s} s`;
}

function share(count: number, total: number): string {
  if (count === 0) return "0%";
  const percent = (count / total) * 100;
  if (percent < 1) return "<1%";
  if (count < total && Math.round(percent) >= 100) return ">99%";
  return `${Math.round(percent)}%`;
}

/** The week's gap histogram as rows to draw, or null when nothing was measured.
 *  `width` is the bar's length as a percentage of the largest bucket's. */
export function gapRows(buckets: GapBucket[] | null | undefined): GapRow[] | null {
  if (!buckets || buckets.length === 0) return null;
  const total = buckets.reduce((sum, b) => sum + b.count, 0);
  if (total <= 0) return null;
  const largest = Math.max(...buckets.map((b) => b.count));
  return buckets.map((bucket) => ({
    label: gapBucketLabel(bucket),
    count: bucket.count,
    percent: share(bucket.count, total),
    width: bucket.count === 0 ? 0 : Math.max(1.5, (bucket.count / largest) * 100),
  }));
}
