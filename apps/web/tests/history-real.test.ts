/**
 * Price history over production data (a snapshot of 2026-11-13, shops
 * anonymised: tests/e2e/fixtures/real-history.json).
 *
 * History began on 2026-11-09 with one seeded baseline row per listing, dated
 * at that listing's last check. So most listings' first point is in October or
 * November, while a stale offer's lone baseline can sit in August. That point
 * used to set when "recording began", and everything before each fresh shop's
 * first point was drawn as a gap labelled "not checked since 13 Nov" (a date
 * after the gap itself). These pin the fix.
 */
import { describe, expect, it } from "vitest";

import type { Product, ProductHistory } from "@/lib/api";
import { buildHistory, dayMonth, lowestLabel, type PriceHistory } from "@/lib/history";

import REAL from "./e2e/fixtures/real-history.json";

const DAY = 86_400_000;
const captured = new Date(REAL.captured_at);
let now = captured;
const TB6600 = "2b43372b-4471-4a32-81c5-9aae1cf32059";
const UT33D = "2c6f64b4-3855-40ec-998d-aa88b4f5ae59";

function built(id: string, at: Date = now): PriceHistory {
  now = at;
  const products = REAL.products as unknown as Record<string, Product>;
  const histories = REAL.histories as unknown as Record<string, ProductHistory>;
  return buildHistory(histories[id], products[id].offers, now) as PriceHistory;
}

/** The earliest point among the offers that are fresh now. */
function firstFreshPoint(id: string): number {
  const products = REAL.products as unknown as Record<string, Product>;
  const histories = REAL.histories as unknown as Record<string, ProductHistory>;
  const fresh = new Set(
    products[id].offers
      .filter((o) => captured.getTime() - Date.parse(o.last_verified_at) <= 45 * DAY)
      .map((o) => o.id),
  );
  return Math.min(
    ...histories[id].offers
      .filter((l) => fresh.has(l.listing_id))
      .flatMap((l) => l.points.map((p) => Date.parse(p.observed_at))),
  );
}

it("UT33D+: no card yet, since its counted shops began recording under 30 days ago", () => {
  // Its first fresh point is 15 Oct; the stale shop's 24 Aug baseline no
  // longer counts as recording, so the 30-day minimum is not yet met.
  expect(built(UT33D, captured)).toBeNull();
});

describe.each([
  ["TB6600", TB6600, 0],
  ["UT33D+ (three days later)", UT33D, 3],
])("%s (production snapshot)", (_, id, later) => {
  const h = built(id, new Date(captured.getTime() + later * DAY));

  it("starts where a counted (fresh) shop's data starts, not at a stale lone point", () => {
    expect(h.kind).toBe("price");
    expect(h.start).toBe(firstFreshPoint(id));
    expect(h.full).toBe(false);
    expect(lowestLabel(h)).toBe(`Lowest since ${dayMonth(h.start)}`);
  });

  it("draws no gap where shops simply had no points yet", () => {
    expect(h.segments.filter((s) => s.price === null)).toEqual([]);
  });

  it("never dates a 'not checked since' after the stretch it labels", () => {
    for (const s of h.segments) {
      if (s.gap === "unchecked") expect(s.checked!).toBeLessThanOrEqual(s.from);
    }
  });
});

describe("the real lowest prices", () => {
  it("TB6600: lowest since 14 Oct is EGP 425; now EGP 425", () => {
    const h = built(TB6600, captured);
    expect(h.lowest?.price).toBe(425);
    expect(h.current.price).toBe(425);
  });

  it("UT33D+: lowest EGP 475 from 23 Oct; now the cheapest in stock, EGP 495", () => {
    const h = built(UT33D, new Date(captured.getTime() + 3 * DAY));
    expect(h.lowest).toMatchObject({ price: 475 });
    expect(dayMonth(h.lowest!.at)).toBe("23 Oct");
    expect(h.current.price).toBe(495);
    // The stale shop's EGP 525 from 24 Aug is not the lowest, and draws nothing.
    expect(h.segments.every((s) => s.from >= h.start)).toBe(true);
  });
});
