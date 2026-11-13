/**
 * Price history on the product page, as plain functions: what the "Price
 * history" card draws and the facts line says, from `GET
 * /products/{id}/history` and the offers on the page. The rules are the
 * owner-approved Phase 2 mockup's (docs/DESIGN.md, "Price history"):
 *
 * - One shop: its own price, dashed while out of stock. Several: the lowest
 *   **in-stock** price among the shops at each moment, naming whose it was;
 *   when no shop had it in stock there is no line, only a shaded gap.
 * - "Lowest" counts in-stock prices only. Offers on request are never drawn.
 * - An out-of-date offer counts only up to its last check: its old price is
 *   not carried to today.
 * - Nothing until RECORDING_MIN_DAYS of recording; "Lowest since {date}"
 *   until the full window; the 12-week stock strip only once 12 weeks are
 *   recorded. With no price at all, only the stock strip (when it can show).
 */
import type { Offer, ProductHistory } from "@/lib/api";
import { needsEach, isStaleOffer } from "@/lib/offers";

const DAY = 86_400_000;
/** The window the page asks for. */
export const HISTORY_DAYS = 90;
/** Less recorded than this and the card is not shown: a line over a week says nothing. */
export const RECORDING_MIN_DAYS = 30;
/** The stock strip: weeks shown, and recorded before it appears. */
export const STRIP_WEEKS = 12;

/** One stretch of the line: from `from` until `to` (ms), one value. */
export type Segment = {
  from: number;
  to: number;
  /** Null: no line (no shop in stock, or the price was on request). */
  price: number | null;
  /** One shop: whether it was in stock (false draws dashed). Several: always
   *  true when priced, since only in-stock prices are drawn. */
  inStock: boolean;
  /** Whose price it was; null for one shop. */
  shop: string | null;
};

export type Lowest = { price: number; at: number; shop: string | null };

export type PriceHistory = {
  kind: "price";
  single: boolean;
  /** Where the chart starts: the window's start, or when recording began. */
  start: number;
  end: number;
  /** Recording covers the whole window ("last 90 days"), else "since {start}". */
  full: boolean;
  segments: Segment[];
  lowest: Lowest | null;
  /** The value now: the last segment's price, null when none in stock. */
  now: number | null;
  /** The prices are prices of one from an offer with a minimum: say "each". */
  each: boolean;
  /** Oldest week first; null until STRIP_WEEKS are recorded. */
  weeks: boolean[] | null;
};

export type StockHistory = {
  kind: "stock";
  single: boolean;
  weeks: boolean[];
};

export type History = PriceHistory | StockHistory;

type Track = {
  shop: string | null;
  /** Points, oldest first, as ms. */
  points: { at: number; price: number | null; inStock: boolean }[];
  /** After this the offer says nothing (its last check, when stale). */
  until: number;
};

function tracks(history: ProductHistory, offers: Offer[], now: Date): Track[] {
  const byId = new Map(offers.map((offer) => [offer.id, offer]));
  return history.offers.flatMap((listing) => {
    const offer = byId.get(listing.listing_id);
    if (!offer || listing.points.length === 0) return [];
    const checked = Date.parse(offer.last_verified_at);
    return [
      {
        shop: offer.supplier?.name ?? null,
        points: listing.points
          .map((p) => ({
            at: Date.parse(p.observed_at),
            price: p.price,
            inStock: p.in_stock && p.available !== false,
          }))
          .filter((p) => !Number.isNaN(p.at))
          .sort((a, b) => a.at - b.at),
        until: isStaleOffer(offer, now) && !Number.isNaN(checked) ? checked : now.getTime(),
      },
    ];
  });
}

/** A track's value at `t`, or null when it says nothing then. */
function valueAt(track: Track, t: number) {
  if (t >= track.until) return null;
  let found: Track["points"][number] | null = null;
  for (const point of track.points) {
    if (point.at <= t) found = point;
    else break;
  }
  return found;
}

/** Whether any offer was in stock at some moment in [from, to). */
function inStockDuring(all: Track[], from: number, to: number): boolean {
  return all.some((track) => {
    const marks = [from, ...track.points.map((p) => p.at).filter((at) => at > from && at < to)];
    return marks.some((t) => valueAt(track, t)?.inStock === true);
  });
}

function weeksOf(all: Track[], end: number): boolean[] {
  return Array.from({ length: STRIP_WEEKS }, (_, i) => {
    const from = end - (STRIP_WEEKS - i) * 7 * DAY;
    return inStockDuring(all, from, from + 7 * DAY);
  });
}

/**
 * What the card shows, or null for no card (and no facts line): no history,
 * or under RECORDING_MIN_DAYS of it.
 */
export function buildHistory(
  history: ProductHistory | null,
  offers: Offer[],
  now: Date = new Date(),
): History | null {
  if (!history) return null;
  const all = tracks(history, offers, now);
  if (all.length === 0) return null;
  const end = now.getTime();
  const recorded = Math.min(...all.map((track) => track.points[0].at));
  if (end - recorded < RECORDING_MIN_DAYS * DAY) return null;
  const windowStart = end - HISTORY_DAYS * DAY;
  const start = Math.max(recorded, windowStart);
  const full = recorded <= windowStart;
  const single = offers.length === 1;
  const weeks = end - recorded >= STRIP_WEEKS * 7 * DAY ? weeksOf(all, end) : null;

  const marks = new Set<number>([start]);
  for (const track of all) {
    for (const point of track.points) if (point.at > start && point.at < end) marks.add(point.at);
    if (track.until > start && track.until < end) marks.add(track.until);
  }
  const times = [...marks].sort((a, b) => a - b);

  const segments: Segment[] = [];
  times.forEach((from, i) => {
    const to = times[i + 1] ?? end;
    let value: Omit<Segment, "from" | "to">;
    if (single) {
      const point = valueAt(all[0], from);
      value = { price: point?.price ?? null, inStock: point?.inStock ?? false, shop: null };
    } else {
      let best: Omit<Segment, "from" | "to"> | null = null;
      for (const track of all) {
        const point = valueAt(track, from);
        if (point?.inStock && point.price !== null && (!best || point.price < best.price!)) {
          best = { price: point.price, inStock: true, shop: track.shop };
        }
      }
      value = best ?? { price: null, inStock: false, shop: null };
    }
    const last = segments[segments.length - 1];
    if (
      last &&
      last.price === value.price &&
      last.inStock === value.inStock &&
      last.shop === value.shop
    ) {
      last.to = to;
    } else {
      segments.push({ from, to, ...value });
    }
  });

  if (!segments.some((s) => s.price !== null && (single || s.inStock))) {
    // Nothing priced to draw: a stock record alone, once it can say 12 weeks.
    return weeks ? { kind: "stock", single, weeks } : null;
  }

  let lowest: Lowest | null = null;
  for (const s of segments) {
    if (s.price !== null && s.inStock && (!lowest || s.price < lowest.price)) {
      lowest = { price: s.price, at: s.from, shop: s.shop };
    }
  }
  const lastSegment = segments[segments.length - 1];
  return {
    kind: "price",
    single,
    start,
    end,
    full,
    segments,
    lowest,
    now: lastSegment.price !== null && (single || lastSegment.inStock) ? lastSegment.price : null,
    each: offers.some(needsEach),
    weeks,
  };
}

/** "15 Aug" (UTC, so the server and a test agree). */
export function dayMonth(ms: number): string {
  return new Date(ms).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/** "Lowest in 90 days", or "Lowest since 24 Aug" before the window is recorded. */
export function lowestLabel(history: PriceHistory): string {
  return history.full
    ? `Lowest in ${HISTORY_DAYS} days`
    : `Lowest since ${dayMonth(history.start)}`;
}

/** "in stock every week of the last 12", "in stock 10 of the last 12 weeks". */
export function weeksText(weeks: boolean[]): string {
  const count = weeks.filter(Boolean).length;
  return count === weeks.length
    ? `in stock every week of the last ${weeks.length}`
    : `in stock ${count} of the last ${weeks.length} weeks`;
}

/** First of each month inside the chart, for the axis. */
export function monthTicks(start: number, end: number): { at: number; label: string }[] {
  const ticks: { at: number; label: string }[] = [];
  const first = new Date(start);
  let month = Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1);
  while (month < end) {
    ticks.push({
      at: month,
      label: new Date(month).toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" }),
    });
    const d = new Date(month);
    month = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  }
  return ticks;
}

/** The price axis: padded so a flat line is not drawn on the frame. */
export function priceScale(segments: Segment[]): { lo: number; hi: number; ticks: number[] } {
  const prices = segments.flatMap((s) => (s.price === null ? [] : [s.price]));
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const pad = Math.max((max - min) * 0.25, max * 0.02, 0.01);
  const ticks = [...new Set(min === max ? [min] : [min, (min + max) / 2, max])];
  return { lo: min - pad, hi: max + pad, ticks };
}
