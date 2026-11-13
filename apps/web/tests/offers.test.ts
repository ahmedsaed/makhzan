/**
 * The comparison rules of the Phase 2 product page (lib/offers.ts), one block
 * per case of the owner-approved mockup. The products are the e2e stub's
 * (tests/e2e/fixtures/phase2.mjs), so the browser tests and these assert the
 * same data.
 */
import { describe, expect, it } from "vitest";

import type { Offer, Product } from "@/lib/api";
import {
  boxSpan,
  breaksText,
  compareOffers,
  comparisonText,
  fitsLabel,
  leadNotes,
  listingsOf,
  minimumLine,
  minimumOrder,
  minimumText,
  needsEach,
  optionsInStock,
  orderOffers,
  partNumbers,
  priceBreakRows,
  quantityLabel,
  rowSpan,
  unitPrice,
  unitPriceText,
} from "@/lib/offers";
import { offerDetails, splitOffers, videoHost } from "@/lib/product";

import { PHASE2 } from "./e2e/fixtures/phase2.mjs";

const CASES = PHASE2 as unknown as Record<string, Product>;
const now = new Date();
const only = (id: string): Offer => CASES[id].offers[0];
const offerOf = (id: string, offerId: string): Offer =>
  CASES[id].offers.find((o) => o.id === offerId)!;
const ids = (offers: Offer[]) => offers.map((o) => o.id);

describe("one shop · options", () => {
  const offer = only("p2-options");

  it("headlines the range across the listing price and its in-stock options", () => {
    expect(boxSpan(offer)).toEqual({ min: 1700, max: 1750 });
  });

  it("counts the options in stock", () => {
    expect(optionsInStock(offer)).toBe(6);
  });

  it("an option without a price never lowers or widens anything", () => {
    expect(unitPrice(offer)).toEqual({ price: 1700, option: null });
  });

  it("uses every option's price when none is in stock", () => {
    const gone = {
      ...offer,
      variants: offer.variants!.map((v) => ({ ...v, in_stock: false })),
    };
    expect(boxSpan(gone)).toEqual({ min: 1700, max: 1750 });
  });

  it("an out-of-stock option never sets the lowest", () => {
    const cheapGone = {
      ...offer,
      variants: [{ title: "Clearance", price: 900, in_stock: false, stock_quantity: null }],
    };
    expect(unitPrice(cheapGone)).toEqual({ price: 1700, option: null });
    // …nor does an option whose stock the shop does not state.
    const unknown = {
      ...offer,
      variants: [{ title: "Maybe", price: 900, in_stock: null, stock_quantity: null }],
    };
    expect(unitPrice(unknown)?.price).toBe(1700);
  });
});

describe("the price of one (the rule the API's min_price shares)", () => {
  const base = only("p2-breaks");
  const opt = (title: string, price: number | null, inStock: boolean | null) => ({
    title,
    price,
    in_stock: inStock,
    stock_quantity: null,
  });
  const recent = new Date(now.getTime() - 3 * 86_400_000).toISOString();

  it("is the cheapest in-stock option when there is one, even above the listing price", () => {
    const offer = {
      ...base,
      price: 360,
      variants: [opt("Type-C", 380, true), opt("Gold", 400, true), opt("Old", 300, false)],
      variants_checked_at: recent,
    };
    expect(unitPrice(offer, now)).toEqual({ price: 380, option: "Type-C" });
  });

  it("names no option when its price is the listing price", () => {
    const offer = {
      ...base,
      price: 47,
      variants: [opt("Standard", 47, true), opt("Deluxe", 60, true)],
      variants_checked_at: recent,
    };
    expect(unitPrice(offer, now)).toEqual({ price: 47, option: null });
  });

  it("falls back to the listing price when no option is in stock with a price", () => {
    const offer = {
      ...base,
      variants: [opt("A", null, true), opt("B", 20, null), opt("C", 10, false)],
      variants_checked_at: recent,
    };
    expect(unitPrice(offer, now)).toEqual({ price: 47, option: null });
  });

  it("ignores options read over 45 days ago", () => {
    const offer = {
      ...base,
      variants: [opt("Cheap", 30, true)],
      variants_checked_at: new Date(now.getTime() - 50 * 86_400_000).toISOString(),
    };
    expect(unitPrice(offer, now)).toEqual({ price: 47, option: null });
  });

  it("never uses a stale offer while any fresh one exists", () => {
    const fresh = { ...base, id: "fresh", price: 60 };
    const stale = {
      ...base,
      id: "stale",
      price: 10,
      last_verified_at: new Date(now.getTime() - 60 * 86_400_000).toISOString(),
    };
    const c = compareOffers([fresh, stale], now);
    expect([c.min, c.max, c.best?.offer.id]).toEqual([60, 60, "fresh"]);
    // Every offer stale: they are all that is left, and they count.
    expect(compareOffers([stale], now).min).toBe(10);
  });

  it("keeps the stock tiers: low stock is in stock, unknown is not known to be gone", () => {
    const low = { ...base, id: "low", stock_signal: "low_stock" as const, price: 50 };
    const unknown = { ...base, id: "unk", stock_signal: "unknown" as const, price: 30 };
    const made = { ...base, id: "mto", stock_signal: "made_to_order" as const, price: 20 };
    const gone = { ...base, id: "gone", stock_signal: "out_of_stock" as const, price: 5 };
    expect(compareOffers([low, unknown, gone], now)).toMatchObject({ state: "in_stock", min: 50 });
    expect(compareOffers([unknown, made, gone], now)).toMatchObject({
      state: "unconfirmed",
      min: 20,
      max: 30,
    });
    expect(compareOffers([gone], now)).toMatchObject({ state: "out_of_stock", min: 5 });
  });

  it("the effective minimum is the larger of minimum and multiple, when over 1", () => {
    expect(minimumOrder({ ...base, min_quantity: 3, multiple_of: 5 })).toBe(5);
    expect(minimumOrder({ ...base, min_quantity: 20, multiple_of: 5 })).toBe(20);
    expect(minimumOrder({ ...base, min_quantity: 1, multiple_of: 1 })).toBeNull();
    expect(minimumOrder({ ...base, min_quantity: null, multiple_of: null })).toBeNull();
  });
});

describe("one shop · minimum order", () => {
  const offer = only("p2-minorder");

  it("keeps the price of one and says each, with the minimum and its total", () => {
    expect(needsEach(offer)).toBe(true);
    expect(minimumOrder(offer)).toBe(10);
    expect(minimumText(offer)).toBe("min. 10 (EGP 1.50)");
    expect(minimumLine(offer)).toBe("min. 10 (EGP 1.50), then in tens");
  });

  it("phrases other steps", () => {
    expect(minimumLine({ ...offer, multiple_of: 5, min_quantity: 20 })).toBe(
      "min. 20 (EGP 3), in multiples of 5",
    );
    expect(minimumLine({ ...offer, multiple_of: 12, min_quantity: 12 })).toBe(
      "min. 12 (EGP 1.80), then in steps of 12",
    );
    expect(minimumLine({ ...offer, multiple_of: null, min_quantity: 3 })).toBe("min. 3 (EGP 0.45)");
    // A shop that sells only in fives sells at least five.
    expect(minimumOrder({ ...offer, multiple_of: 5, min_quantity: null })).toBe(5);
  });

  it("an offer sold singly says no each and has no minimum", () => {
    const single = only("p2-breaks");
    expect(needsEach(single)).toBe(false);
    expect(minimumText(single)).toBeNull();
  });

  it("states the manufacturer's part number with whose listing it is", () => {
    expect(partNumbers(null, CASES["p2-minorder"].offers)).toEqual({
      alsoStatedBy: [],
      stated: { value: "FRC0603F6803TS", shops: ["Cairo Makers"] },
      disagree: null,
    });
    expect(listingsOf(["Cairo Makers"])).toBe("Cairo Makers's listing");
  });
});

describe("one shop · quantity prices", () => {
  const offer = only("p2-breaks");

  it("lists the tiers from one, as the shop states them", () => {
    const rows = priceBreakRows(offer);
    expect(rows.map(quantityLabel)).toEqual(["1–9", "10–49", "50 or more"]);
    expect(rows.map((r) => r.price)).toEqual([47, 44, 42]);
    expect(breaksText(offer)).toBe("EGP 44 from 10, EGP 42 from 50");
  });

  it("starts at the minimum when there is one, and drops tiers under it", () => {
    const rows = priceBreakRows({
      ...offer,
      min_quantity: 10,
      price_breaks: [
        { min_quantity: 5, price: 46 },
        { min_quantity: 11, price: 44 },
      ],
    });
    expect(rows.map(quantityLabel)).toEqual(["10", "11 or more"]);
  });

  it("has no table without breaks or without a price", () => {
    expect(priceBreakRows(only("p2-options"))).toEqual([]);
    expect(priceBreakRows({ ...offer, price: null })).toEqual([]);
  });
});

describe("one shop · price on request", () => {
  const offer = only("p2-por");

  it("has no price to show or compare: never EGP 0", () => {
    expect(boxSpan(offer)).toBeNull();
    expect(rowSpan(offer)).toBeNull();
    expect(unitPrice(offer)).toBeNull();
  });
});

describe("Fits", () => {
  it("names up to two models and folds more", () => {
    expect(fitsLabel(["K2 Plus"])).toBe("Fits K2 Plus");
    expect(fitsLabel(["Ender 3", "Anet A8"])).toBe("Fits Ender 3, Anet A8");
    expect(fitsLabel(only("p2-badges").compatible_with!)).toBe("Fits 19 models");
    expect(fitsLabel([])).toBeNull();
  });
});

describe("several shops · mixed minimum orders", () => {
  const c = compareOffers(CASES["p2-mixedmin"].offers, now);

  it("compares by the price of one, so the shop selling in tens leads", () => {
    expect(c.min).toBe(0.15);
    expect(c.max).toBe(2);
    expect(c.best?.offer.supplier?.name).toBe("Cairo Makers");
  });

  it("the range reads each as soon as any offer in it has a minimum", () => {
    expect(c.each).toBe(true);
  });

  it("the button and bar carry each and the minimum with its total", () => {
    expect(unitPriceText(c.best!)).toBe("EGP 0.15 each");
    expect(leadNotes(c.best!)).toEqual(["min. 10 (EGP 1.50)"]);
  });

  it("without a minimum in the range there is no each", () => {
    expect(compareOffers(CASES["p2-cheapopt"].offers, now).each).toBe(false);
  });
});

describe("several shops · some offers on request", () => {
  const offers = CASES["p2-somepor"].offers;
  const c = compareOffers(offers, now);

  it("leaves offers on request out of the range and the button", () => {
    expect(c.min).toBe(1450);
    expect(c.max).toBe(1500);
    expect(c.best?.offer.supplier?.name).toBe("Giza Robotics");
  });

  it("counts them apart: the summary adds “· 1 more on request”", () => {
    expect(comparisonText(c)).toBe("2 offers in stock at 2 shops · 1 more on request");
  });

  it("sorts an in-stock offer on request after every priced one", () => {
    expect(ids(splitOffers(offers, now).listed)).toEqual([
      "o2-sp-giza",
      "o2-sp-nile",
      "o2-sp-sphinx",
    ]);
  });
});

describe("several shops · all on request", () => {
  const c = compareOffers(CASES["p2-allpor"].offers, now);

  it("has no range, and says prices are on request", () => {
    expect(c.min).toBeNull();
    expect(c.best).toBeNull();
    expect(comparisonText(c)).toBe("2 offers in stock at 2 shops, prices on request");
  });

  it("the button opens the most recently checked in-stock offer", () => {
    expect(c.onRequest[0].supplier?.name).toBe("Giza Robotics");
    expect(orderOffers(CASES["p2-allpor"].offers)[0].supplier?.name).toBe("Giza Robotics");
  });
});

describe("several shops · a cheaper option at one shop", () => {
  const offers = CASES["p2-cheapopt"].offers;
  const c = compareOffers(offers, now);

  it("counts each offer's lowest in-stock option", () => {
    expect(c.min).toBe(320);
    expect(c.max).toBe(355);
    expect(c.best).toMatchObject({ price: 320, option: "Without headers" });
  });

  it("names the option wherever the price leads", () => {
    expect(leadNotes(c.best!)).toEqual(["“Without headers” option"]);
    expect(unitPriceText(c.best!)).toBe("EGP 320");
  });

  it("sorts by that price, and the row shows the span of all options", () => {
    expect(ids(orderOffers(offers))[0]).toBe("o2-co-cairo");
    expect(rowSpan(offerOf("p2-cheapopt", "o2-co-cairo"))).toEqual({ min: 320, max: 380 });
  });
});

describe("several shops · quantity prices, a stock count, a stale lowest", () => {
  const offers = CASES["p2-volume"].offers;
  const c = compareOffers(offers, now);

  it("a stale offer counts nowhere, even as the lowest", () => {
    expect(c.min).toBe(55);
    expect(c.max).toBe(90);
    expect(c.best?.offer.supplier?.name).toBe("Giza Robotics");
    const split = splitOffers(offers, now);
    expect(ids(split.stale)).toEqual(["o2-v-mans"]);
    expect(ids(split.outOfStock)).toEqual(["o2-v-alex"]);
  });

  it("adds one hint line when a quantity price beats every price of one", () => {
    expect(c.hint).toEqual({ shop: "Giza Robotics", quantity: 100, price: 35, currency: "EGP" });
  });

  it("gives no hint when no quantity price beats the lowest price of one", () => {
    const giza = offerOf("p2-volume", "o2-v-giza");
    const weak = { ...giza, price_breaks: [{ min_quantity: 20, price: 56 }] };
    const delta = offerOf("p2-volume", "o2-v-delta");
    expect(compareOffers([weak, delta], now).hint).toBeNull();
  });

  it("a quantity price never changes the range, the order or the button", () => {
    expect(ids(orderOffers(offers)).slice(0, 3)).toEqual(["o2-v-mans", "o2-v-giza", "o2-v-delta"]);
  });
});

describe("several shops · part numbers", () => {
  it("disagreeing shops: none stands alone; makhzan's own adds who also states it", () => {
    expect(partNumbers("NE555", CASES["p2-mfrs"].offers)).toEqual({
      alsoStatedBy: ["Delta Components"],
      stated: null,
      disagree: ["NE555P", "NE555"],
    });
  });

  it("one stated number different from makhzan's own gets its own line", () => {
    expect(partNumbers("TB6600", CASES["p2-multi"].offers)).toEqual({
      alsoStatedBy: [],
      stated: { value: "TB6600HG", shops: ["Cairo Makers"] },
      disagree: null,
    });
  });

  it("folds case and spaces, and names several shops", () => {
    const offers = CASES["p2-mfrs"].offers.map((o) => ({ ...o, mfr_part_number: "ne 555" }));
    const result = partNumbers("NE555", offers);
    expect(result.disagree).toBeNull();
    expect(result.stated).toBeNull();
    expect(result.alsoStatedBy).toEqual(["Cairo Makers", "Delta Components", "Nile Parts"]);
    expect(listingsOf(["A", "B"])).toBe("A's and B's listings");
  });

  it("says nothing when no shop states one", () => {
    expect(partNumbers("XL6009", CASES["p2-breaks"].offers)).toEqual({
      alsoStatedBy: [],
      stated: null,
      disagree: null,
    });
  });
});

describe("several shops · Fits differ, ships from abroad", () => {
  const c = compareOffers(CASES["p2-fits"].offers, now);

  it("the cheapest offer ships from abroad, and the button and bar repeat it", () => {
    expect(c.best?.offer.supplier?.name).toBe("Bazaar Hub");
    expect(leadNotes(c.best!)).toEqual(["ships from abroad"]);
  });

  it("each row keeps its own list", () => {
    expect(fitsLabel(offerOf("p2-fits", "o2-f-giza").compatible_with!)).toBe(
      "Fits Ender 3, Anet A8",
    );
    expect(fitsLabel(offerOf("p2-fits", "o2-f-sphinx").compatible_with!)).toBe("Fits 4 models");
  });
});

describe("several shops · mixed features (TB6600)", () => {
  const offers = CASES["p2-multi"].offers;
  const c = compareOffers(offers, now);

  it("compares the fresh in-stock offers", () => {
    expect(comparisonText(c)).toBe("4 offers in stock at 4 shops");
    expect([c.min, c.max]).toEqual([425, 550]);
    expect(c.hint).toMatchObject({ shop: "Giza Robotics", quantity: 50, price: 405 });
  });

  it("the row with options shows their span; the summary their lowest in stock", () => {
    expect(rowSpan(offerOf("p2-multi", "o2-tb-sphinx"))).toEqual({ min: 550, max: 620 });
    expect(c.priced.find((p) => p.offer.id === "o2-tb-sphinx")?.price).toBe(550);
  });

  it("folds out-of-stock and stale offers apart", () => {
    const split = splitOffers(offers, now);
    expect(ids(split.outOfStock)).toEqual(["o2-tb-cairo"]);
    expect(ids(split.stale)).toEqual(["o2-tb-bazaar"]);
  });
});

describe("videos (What the shops say)", () => {
  it("are kept from a shop's listing, https only, named by their host", () => {
    const offer = {
      ...only("p2-breaks"),
      videos: [
        { url: "https://youtu.be/abc", label: null },
        { url: "http://example.test/v.mp4", label: "plain" },
      ],
    };
    expect(offerDetails(offer)?.videos).toEqual([
      { url: "https://youtu.be/abc", label: "Video", host: "YouTube" },
    ]);
    expect(videoHost("https://www.youtube.com/watch?v=1")).toBe("YouTube");
    expect(videoHost("https://m.facebook.com/x")).toBe("Facebook");
    expect(videoHost("https://cdn.shop.test/v")).toBe("cdn.shop.test");
  });
});

describe("states before Phase 2 still read the same", () => {
  it("unconfirmed and out of stock keep their wording", () => {
    const base = only("p2-breaks");
    const unknown = { ...base, stock_signal: "unknown" as const };
    expect(comparisonText(compareOffers([unknown], now))).toBe(
      "1 offer at 1 shop, stock not confirmed",
    );
    const gone = CASES["p2-mixedmin"].offers.map((o) => ({
      ...o,
      stock_signal: "out_of_stock" as const,
    }));
    expect(comparisonText(compareOffers(gone, now))).toBe("Out of stock at all 3 shops");
    // Out of stock everywhere: no quantity hint is offered.
    expect(compareOffers(gone, now).hint).toBeNull();
  });
});
