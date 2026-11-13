/**
 * Price history on the product page, as plain functions: what the "Price
 * history" card draws and the facts line says, from `GET
 * /products/{id}/history` and the offers on the page. The rules are the
 * owner-approved Phase 2 mockup's (docs/DESIGN.md, "Price history"):
 *
 * - One shop: its own price, dashed while out of stock. Several: the lowest
 *   **in-stock** price among the shops at each moment, naming whose it was;
 *   when no shop had it in stock there is no line, only a shaded gap. Every
 *   gap says why: out of stock, price on request, not listed (archived), or
 *   not checked since the offer's last check.
 * - It follows each shop's **listing** price; option prices are not recorded
 *   yet (a stopgap, said on the card).
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

/** Why there is no line for a stretch. */
export type GapReason =
  /** Past the offer's last check: it is out of date, and says nothing now. */
  | "unchecked"
  /** In stock, with the price on request. */
  | "on-request"
  /** Out of stock (several shops: none in stock). */
  | "out-of-stock"
  /** The shop had stopped listing it (archived). */
  | "unlisted";

/** One stretch of the line: from `from` until `to` (ms), one value. */
export type Segment = {
  from: number;
  to: number;
  /** Null: no line; `gap` says why. */
  price: number | null;
  /** One shop: whether it was in stock (false draws dashed). Several: always
   *  true when priced, since only in-stock prices are drawn. */
  inStock: boolean;
  /** Whose price it was; null for one shop. */
  shop: string | null;
  /** Why there is no price, when there is none. */
  gap: GapReason | null;
  /** For an "unchecked" gap: the last check it dates from. */
  checked: number | null;
  /** The shop whose price this is is now out of date (C2b): its offer counts
   *  only up to its last check, and a "Lowest" from it says so. */
  outOfDate: boolean;
};

export type Lowest = {
  price: number;
  at: number;
  shop: string | null;
  /** Its shop's offer is now out of date: "(now out of date)" (owner's rule). */
  outOfDate: boolean;
};

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
  /** The last stretch: what "Now" says (a price, or why there is none). */
  current: Segment;
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

type Point = { at: number; price: number | null; inStock: boolean; available: boolean };

type Track = {
  shop: string | null;
  /** Points, oldest first, as ms. */
  points: Point[];
  /** After this the offer says nothing (its last check, when stale). */
  until: number;
  /** Older points were dropped to the API's cap: recording began before the first. */
  truncated: boolean;
  /** The offer is out of date now (C2b). */
  stale: boolean;
};

function tracks(history: ProductHistory, offers: Offer[], now: Date): Track[] {
  const byId = new Map(offers.map((offer) => [offer.id, offer]));
  return history.offers.flatMap((listing) => {
    const offer = byId.get(listing.listing_id);
    if (!offer || listing.points.length === 0) return [];
    const checked = Date.parse(offer.last_verified_at);
    const stale = isStaleOffer(offer, now);
    return [
      {
        shop: offer.supplier?.name ?? null,
        points: listing.points
          .map((p) => ({
            at: Date.parse(p.observed_at),
            price: p.price,
            inStock: p.in_stock,
            available: p.available !== false,
          }))
          .filter((p) => !Number.isNaN(p.at))
          .sort((a, b) => a.at - b.at),
        until: stale && !Number.isNaN(checked) ? checked : now.getTime(),
        truncated: listing.truncated === true,
        stale,
      },
    ];
  });
}

/** A track's point in force at `t`, or null before its first or after its last check. */
function valueAt(track: Track, t: number): Point | null {
  if (t >= track.until) return null;
  let found: Point | null = null;
  for (const point of track.points) {
    if (point.at <= t) found = point;
    else break;
  }
  return found;
}

/** In stock and listed: what the stock strip counts. */
function stocked(point: Point | null): boolean {
  return point !== null && point.inStock && point.available;
}

/** Whether any offer was in stock at some moment in [from, to). */
function inStockDuring(all: Track[], from: number, to: number): boolean {
  return all.some((track) => {
    const marks = [from, ...track.points.map((p) => p.at).filter((at) => at > from && at < to)];
    return marks.some((t) => stocked(valueAt(track, t)));
  });
}

function weeksOf(all: Track[], end: number): boolean[] {
  return Array.from({ length: STRIP_WEEKS }, (_, i) => {
    const from = end - (STRIP_WEEKS - i) * 7 * DAY;
    return inStockDuring(all, from, from + 7 * DAY);
  });
}

type Value = Omit<Segment, "from" | "to">;

const gap = (reason: GapReason, checked: number | null = null): Value => ({
  price: null,
  inStock: false,
  shop: null,
  gap: reason,
  checked,
  outOfDate: false,
});

/** One shop at `t`: its own price, dashed while out of stock; otherwise why not. */
function singleValue(track: Track, t: number): Value {
  if (t >= track.until) return gap("unchecked", track.until);
  const point = valueAt(track, t);
  if (!point) return gap("unchecked", track.until);
  if (!point.available) return gap("unlisted");
  if (point.price === null) return gap(point.inStock ? "on-request" : "out-of-stock");
  return {
    price: point.price,
    inStock: point.inStock,
    shop: null,
    gap: null,
    checked: null,
    outOfDate: track.stale,
  };
}

/**
 * Several shops at `t`: the lowest in-stock price, naming whose it is. At an
 * equal price the shop already shown keeps it, else the first by name, so the
 * line never depends on the order the API lists offers in.
 */
function lowestValue(all: Track[], t: number, previous: string | null): Value {
  const priced = all.flatMap((track) => {
    const point = valueAt(track, t);
    return stocked(point) && point!.price !== null
      ? [{ price: point!.price as number, shop: track.shop, stale: track.stale }]
      : [];
  });
  if (priced.length > 0) {
    const low = Math.min(...priced.map((p) => p.price));
    const tied = priced.filter((p) => p.price === low);
    const names = tied.map((p) => p.shop ?? "");
    const shop = names.includes(previous ?? "\u0000")
      ? previous
      : [...names].sort((a, b) => a.localeCompare(b))[0] || null;
    const outOfDate = tied.find((p) => (p.shop ?? "") === (shop ?? ""))?.stale ?? false;
    return { price: low, inStock: true, shop, gap: null, checked: null, outOfDate };
  }
  const points = all.map((track) => valueAt(track, t));
  if (points.some(stocked)) return gap("on-request");
  if (points.some((p) => p?.available)) return gap("out-of-stock");
  if (points.some((p) => p !== null)) return gap("unlisted");
  // Nobody has a value: the shops that had one are past their last check.
  // The date is the latest of *those* checks, never a shop that has not
  // started yet (whose `until` is today).
  const ended = all.filter((track) => track.points[0].at <= t && t >= track.until);
  return gap("unchecked", ended.length ? Math.max(...ended.map((track) => track.until)) : null);
}

const same = (a: Value, b: Value) =>
  a.price === b.price &&
  a.inStock === b.inStock &&
  a.shop === b.shop &&
  a.gap === b.gap &&
  a.checked === b.checked &&
  a.outOfDate === b.outOfDate;

/**
 * What the card shows, or null for no card (and no facts line): no history,
 * or under RECORDING_MIN_DAYS of it.
 *
 * History follows each shop's **listing** price: option prices are not
 * recorded yet, so an offer priced by an option on the page is drawn at its
 * listing price here (a stopgap, said on the card, until they are).
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
  // When recording began, read from the offers that count (C2b): the fresh
  // ones when any is fresh. A stale offer's lone point (its seeded baseline,
  // dated at its last check months ago) must not stretch the chart back to a
  // time when no counted shop had a point: that stretch would be all gap. A
  // truncated track began before its first point: recording covers the window.
  const fresh = all.filter((track) => !track.stale);
  const counted = fresh.length > 0 ? fresh : all;
  const recorded = Math.min(
    ...counted.map((track) => (track.truncated ? -Infinity : track.points[0].at)),
  );
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
    const last = segments[segments.length - 1];
    const value = single ? singleValue(all[0], from) : lowestValue(all, from, last?.shop ?? null);
    if (last && same(last, value)) last.to = to;
    else segments.push({ from, to, ...value });
  });

  if (!segments.some((s) => s.price !== null)) {
    // Nothing priced to draw: a stock record alone, once it can say 12 weeks.
    return weeks ? { kind: "stock", single, weeks } : null;
  }

  let lowest: Lowest | null = null;
  for (const s of segments) {
    if (s.price !== null && s.inStock && (!lowest || s.price < lowest.price)) {
      lowest = { price: s.price, at: s.from, shop: s.shop, outOfDate: s.outOfDate };
    }
  }
  return {
    kind: "price",
    single,
    start,
    end,
    full,
    segments,
    lowest,
    current: segments[segments.length - 1],
    each: offers.some(needsEach),
    weeks,
  };
}

/** Dates as Egypt reads them: the shops and their buyers are in Cairo. */
const ZONE = "Africa/Cairo";

/** "15 Aug", in Cairo time. */
export function dayMonth(ms: number): string {
  return new Date(ms).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: ZONE,
  });
}

/** What a stretch without a line says, in the table and as "Now". */
export function gapText(segment: Segment, single: boolean): string {
  switch (segment.gap) {
    case "on-request":
      return "Price on request";
    case "unlisted":
      return "Not listed";
    case "unchecked":
      return segment.checked ? `Not checked since ${dayMonth(segment.checked)}` : "Not checked";
    default:
      return single ? "Out of stock" : "None in stock";
  }
}

/** The label inside a shaded gap on the chart. */
export function gapLabel(segment: Segment, single: boolean): string {
  switch (segment.gap) {
    case "on-request":
      return "price on request";
    case "unlisted":
      return "not listed";
    case "unchecked":
      return segment.checked ? `not checked since ${dayMonth(segment.checked)}` : "not checked";
    default:
      return single ? "out of stock" : "none in stock";
  }
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
      label: new Date(month).toLocaleDateString("en-GB", { month: "short", timeZone: ZONE }),
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
  // The middle tick rounded as the axis prints it, so its label is its place.
  const mid = (min + max) / 2;
  const middle = max >= 10 ? Math.round(mid) : Math.round(mid * 100) / 100;
  const ticks = [...new Set(min === max ? [min] : [min, middle, max])];
  return { lo: min - pad, hi: max + pad, ticks };
}
