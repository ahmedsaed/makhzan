/**
 * Price history rules (lib/history.ts), over the e2e stub's Phase 2 cases
 * (tests/e2e/fixtures/phase2.mjs) and a few hand-made edges.
 */
import { describe, expect, it } from "vitest";

import type { Product, ProductHistory } from "@/lib/api";
import {
  buildHistory,
  dayMonth,
  lowestLabel,
  monthTicks,
  priceScale,
  weeksText,
  type PriceHistory,
} from "@/lib/history";

import { PHASE2, PHASE2_HISTORY } from "./e2e/fixtures/phase2.mjs";

const DAY = 86_400_000;
const CASES = PHASE2 as unknown as Record<string, Product>;
const RECORDED = PHASE2_HISTORY as unknown as Record<
  string,
  Record<string, ProductHistory["offers"][number]["points"]>
>;
const now = new Date();

function historyOf(id: string): ProductHistory {
  return {
    product_id: id,
    since: new Date(now.getTime() - 90 * DAY).toISOString(),
    offers: CASES[id].offers.map((offer) => ({
      listing_id: offer.id,
      since: "",
      points: RECORDED[id]?.[offer.id] ?? [],
    })),
  };
}
const built = (id: string) => buildHistory(historyOf(id), CASES[id].offers, now);
const priced = (id: string) => built(id) as PriceHistory;
const daysAgo = (ms: number) => Math.round((now.getTime() - ms) / DAY);

describe("when there is a card", () => {
  it("none without history", () => {
    expect(buildHistory(null, CASES["p2-por"].offers, now)).toBeNull();
    expect(built("p2-por")).toBeNull();
  });

  it("none under 30 days of recording", () => {
    expect(built("p2-mfrs")).toBeNull();
  });

  it("from 30 days: 'Lowest since {date}' and no 12-week strip yet", () => {
    const h = priced("p2-breaks");
    expect(h.kind).toBe("price");
    expect(h.full).toBe(false);
    expect(daysAgo(h.start)).toBe(81);
    expect(lowestLabel(h)).toBe(`Lowest since ${dayMonth(h.start)}`);
    expect(h.weeks).toBeNull();
    expect(h.lowest).toMatchObject({ price: 45, shop: null });
    expect(h.now).toBe(47);
  });

  it("from 90 days: 'Lowest in 90 days' and the strip", () => {
    const h = priced("p2-options");
    expect(h.full).toBe(true);
    expect(lowestLabel(h)).toBe("Lowest in 90 days");
    expect(h.weeks).toHaveLength(12);
  });
});

describe("one shop", () => {
  const h = priced("p2-options");

  it("draws its own price, out-of-stock stretches dashed (not in stock)", () => {
    expect(h.single).toBe(true);
    expect(h.segments.map((s) => [s.price, s.inStock])).toEqual([
      [1650, true],
      [1650, false],
      [1700, true],
      [1700, false],
      [1700, true],
    ]);
  });

  it("counts only in-stock prices as the lowest", () => {
    expect(h.lowest?.price).toBe(1650);
    expect(h.now).toBe(1700);
  });

  it("counts weeks with stock", () => {
    expect(weeksText(h.weeks!)).toBe("in stock 10 of the last 12 weeks");
  });
});

describe("several shops", () => {
  it("draws the lowest in-stock price, naming whose it was", () => {
    const h = priced("p2-histmulti");
    expect(h.segments.map((s) => [s.price, s.shop])).toEqual([
      [330, "Nile Parts"],
      [315, "Delta Components"],
      [null, null],
      [340, "Giza Robotics"],
      [320, "Delta Components"],
    ]);
    expect(h.lowest).toMatchObject({ price: 315, shop: "Delta Components" });
    expect(daysAgo(h.lowest!.at)).toBe(72);
  });

  it("a stretch with no shop in stock is a gap, and weeks count any shop", () => {
    const h = priced("p2-histmulti");
    const gap = h.segments.find((s) => s.price === null)!;
    expect([daysAgo(gap.from), daysAgo(gap.to)]).toEqual([58, 41]);
    expect(weeksText(h.weeks!)).toBe("in stock 10 of the last 12 weeks");
  });

  it("a stale offer counts only up to its last check", () => {
    const h = priced("p2-volume");
    expect(h.lowest).toMatchObject({ price: 48, shop: "Mansoura Electronics" });
    const after = h.segments.find((s) => s.shop === "Giza Robotics")!;
    expect(daysAgo(after.from)).toBe(81);
    expect(h.now).toBe(55);
  });

  it("an out-of-date shop's price is not carried to today (TB6600)", () => {
    const h = priced("p2-multi");
    // Bazaar Hub's 400 (stale, checked 81 days ago) leads only until then.
    expect(h.segments[0]).toMatchObject({ price: 400, shop: "Bazaar Hub" });
    expect(daysAgo(h.segments[0].to)).toBe(81);
    expect(h.segments.at(-1)).toMatchObject({ price: 425 });
    expect(h.lowest?.price).toBe(400);
  });

  it("offers on request are never drawn", () => {
    const h = priced("p2-somepor");
    expect(h.segments.every((s) => s.price !== null)).toBe(true);
    expect(h.lowest).toMatchObject({ price: 1450, shop: "Giza Robotics" });
  });

  it("with nothing priced, a stock record alone", () => {
    const h = built("p2-allpor");
    expect(h).toEqual({ kind: "stock", single: false, weeks: expect.any(Array) });
    expect(weeksText((h as { weeks: boolean[] }).weeks)).toBe("in stock every week of the last 12");
  });

  it("…and nothing at all before 12 weeks are recorded", () => {
    const offers = CASES["p2-allpor"].offers;
    const short: ProductHistory = {
      ...historyOf("p2-allpor"),
      offers: offers.map((offer) => ({
        listing_id: offer.id,
        since: "",
        points: [
          {
            observed_at: new Date(now.getTime() - 40 * DAY).toISOString(),
            price: null,
            currency: "EGP",
            stock_signal: "in_stock",
            in_stock: true,
          },
        ],
      })),
    };
    expect(buildHistory(short, offers, now)).toBeNull();
  });

  it("a minimum order makes the line a price of one: each", () => {
    expect(priced("p2-mixedmin").each).toBe(true);
    expect(priced("p2-histmulti").each).toBe(false);
  });
});

describe("axes", () => {
  it("months start on the first, inside the chart", () => {
    const start = Date.UTC(2026, 7, 15);
    const end = Date.UTC(2026, 10, 13);
    expect(monthTicks(start, end).map((t) => t.label)).toEqual(
      ["Sept", "Oct", "Nov"].map((m) =>
        new Date(Date.UTC(2026, ["Sept", "Oct", "Nov"].indexOf(m) + 8, 1)).toLocaleDateString(
          "en-GB",
          { month: "short", timeZone: "UTC" },
        ),
      ),
    );
  });

  it("the price scale pads a flat line off the frame", () => {
    const flat = priceScale([{ from: 0, to: 1, price: 100, inStock: true, shop: null }]);
    expect(flat.ticks).toEqual([100]);
    expect(flat.lo).toBeLessThan(100);
    expect(flat.hi).toBeGreaterThan(100);
  });
});
