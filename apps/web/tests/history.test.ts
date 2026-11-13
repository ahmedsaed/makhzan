/**
 * Price history rules (lib/history.ts), over the e2e stub's Phase 2 cases
 * (tests/e2e/fixtures/phase2.mjs) and a few hand-made edges.
 */
import { describe, expect, it } from "vitest";

import type { Product, ProductHistory } from "@/lib/api";
import {
  buildHistory,
  dayMonth,
  gapLabel,
  gapText,
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
const point = (days: number, price: number | null, inStock: boolean) => ({
  observed_at: new Date(now.getTime() - days * DAY).toISOString(),
  price,
  currency: "EGP",
  stock_signal: (inStock ? "in_stock" : "out_of_stock") as "in_stock" | "out_of_stock",
  in_stock: inStock,
  available: true,
});

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
    expect(h.current.price).toBe(47);
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
    expect(h.current.price).toBe(1700);
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

  it("a stale offer counts only up to its last check, and its Lowest says so", () => {
    const h = priced("p2-volume");
    // Owner's rule: it still counts as the lowest, flagged as now out of date.
    expect(h.lowest).toMatchObject({ price: 48, shop: "Mansoura Electronics", outOfDate: true });
    const after = h.segments.find((s) => s.shop === "Giza Robotics")!;
    expect(daysAgo(after.from)).toBe(81);
    expect(h.current.price).toBe(55);
  });

  it("a fresh shop's Lowest is not flagged", () => {
    expect(priced("p2-histmulti").lowest?.outOfDate).toBe(false);
  });

  it("TB6600: the lowest moves between shops, as the mockup draws it", () => {
    const h = priced("p2-multi");
    expect(h.segments.map((s) => [s.price, s.shop])).toEqual([
      [440, "Nile Parts"],
      [430, "Nile Parts"],
      [425, "Giza Robotics"],
      [419, "Giza Robotics"],
      [429, "Giza Robotics"],
      [425, "Delta Components"],
    ]);
    expect(h.lowest).toMatchObject({ price: 419, shop: "Giza Robotics", outOfDate: false });
  });

  it("at an equal price the shop already shown keeps the line, never API order", () => {
    const [a, b] = CASES["p2-mixedmin"].offers;
    const pts = (price: number) => [point(100, price, true)];
    const forward = {
      ...historyOf("p2-mixedmin"),
      offers: [
        { listing_id: a.id, since: "", points: pts(5) },
        { listing_id: b.id, since: "", points: [point(100, 7, true), point(50, 5, true)] },
      ],
    };
    const backward = { ...forward, offers: [...forward.offers].reverse() };
    for (const history of [forward, backward]) {
      const h = buildHistory(history, [a, b], now) as PriceHistory;
      expect(h.segments.map((s) => s.shop)).toEqual(["Cairo Makers"]);
    }
    // Delta shown first keeps the line when Cairo Makers comes down to its price.
    const swapped = {
      ...forward,
      offers: [
        { listing_id: a.id, since: "", points: [point(100, 7, true), point(50, 5, true)] },
        { listing_id: b.id, since: "", points: pts(5) },
      ],
    };
    const h = buildHistory(swapped, [a, b], now) as PriceHistory;
    expect(h.segments.map((s) => s.shop)).toEqual(["Delta Components"]);
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

describe("why a stretch has no line", () => {
  const offer = CASES["p2-breaks"].offers[0];
  const one = (points: ReturnType<typeof point>[], extra: Partial<typeof offer> = {}) =>
    buildHistory(
      {
        product_id: "x",
        since: "",
        offers: [{ listing_id: offer.id, since: "", points }],
      },
      [{ ...offer, ...extra }],
      now,
    ) as PriceHistory;

  it("one shop out of date: 'not checked since', never 'on request' or 'none in stock'", () => {
    const checked = new Date(now.getTime() - 60 * DAY).toISOString();
    const h = one([point(100, 40, true)], { last_verified_at: checked });
    expect(h.segments.map((s) => [s.price, s.gap])).toEqual([
      [40, null],
      [null, "unchecked"],
    ]);
    expect(gapText(h.current, true)).toBe(`Not checked since ${dayMonth(Date.parse(checked))}`);
    expect(gapLabel(h.current, true)).toMatch(/^not checked since /);
  });

  it("an archived stretch is a gap, 'not listed', never a dashed line at the old price", () => {
    const h = one([
      point(100, 40, true),
      { ...point(60, 40, false), available: false },
      point(40, 42, true),
    ]);
    expect(h.segments.map((s) => [s.price, s.gap])).toEqual([
      [40, null],
      [null, "unlisted"],
      [42, null],
    ]);
    expect(gapText(h.segments[1], true)).toBe("Not listed");
  });

  it("in stock on request: Now reads 'Price on request'", () => {
    const h = one([point(100, 40, true), point(40, null, true)]);
    expect(h.current).toMatchObject({ price: null, gap: "on-request" });
    expect(gapText(h.current, true)).toBe("Price on request");
  });

  it("several shops: none in stock reads so", () => {
    const h = priced("p2-histmulti");
    const gap = h.segments.find((s) => s.price === null)!;
    expect(gap.gap).toBe("out-of-stock");
    expect(gapText(gap, false)).toBe("None in stock");
  });

  it("a truncated history began before its first point: the full window", () => {
    const h = buildHistory(
      {
        product_id: "x",
        since: "",
        offers: [
          { listing_id: offer.id, since: "", points: [point(50, 40, true)], truncated: true },
        ],
      },
      [offer],
      now,
    ) as PriceHistory;
    expect(h.full).toBe(true);
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
          { month: "short", timeZone: "Africa/Cairo" },
        ),
      ),
    );
  });

  it("the price scale pads a flat line off the frame", () => {
    const seg = {
      from: 0,
      to: 1,
      inStock: true,
      shop: null,
      gap: null,
      checked: null,
      outOfDate: false,
    };
    const flat = priceScale([{ ...seg, price: 100 }]);
    expect(flat.ticks).toEqual([100]);
    expect(flat.lo).toBeLessThan(100);
    expect(flat.hi).toBeGreaterThan(100);
    // The middle tick is the round number its label prints.
    expect(
      priceScale([
        { ...seg, price: 315 },
        { ...seg, price: 340 },
      ]).ticks,
    ).toEqual([315, 328, 340]);
    expect(
      priceScale([
        { ...seg, price: 0.15 },
        { ...seg, price: 0.2 },
      ]).ticks,
    ).toEqual([0.15, 0.18, 0.2]);
  });
});
