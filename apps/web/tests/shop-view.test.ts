/**
 * The shop view's rules (lib/shop-view.ts) and the report form's AI-first
 * order (lib/report.ts). Shops are fictional.
 */
import { describe, expect, it } from "vitest";

import type { Offer, Product, StockSignal } from "@/lib/api";
import { detailSources, galleryPhotos } from "@/lib/product";
import { blankForm, offersToList, reportContextOf } from "@/lib/report";
import {
  aiMatchedCount,
  aiNoteText,
  detailIndexOf,
  initialPick,
  isAiMatched,
  photoIndexOf,
  shopLead,
  shopParam,
  shopViewUrl,
} from "@/lib/shop-view";

const NOW = new Date("2026-11-16T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW.getTime() - days * 86_400_000).toISOString();

function offer(
  id: string,
  shop: string,
  price: number | null,
  {
    stock = "in_stock" as StockSignal,
    images = [] as string[],
    ai = false,
    age = 2,
    url = true,
  } = {},
): Offer {
  return {
    id,
    title_en: `${shop} title ${id}`,
    title_ar: null,
    price,
    currency: "EGP",
    stock_signal: stock,
    source_url: url ? `https://${shop}.test/${id}` : null,
    images,
    last_verified_at: daysAgo(age),
    matched_by: ai ? "ai" : "rules",
    supplier: {
      id: shop,
      slug: shop,
      name: shop.toUpperCase(),
      name_ar: null,
      area: null,
      governorate: null,
      website_url: null,
    },
  };
}

function product(offers: Offer[], extra: Partial<Product> = {}): Product {
  return {
    id: "p1",
    part_number: null,
    title_en: "Stepper driver",
    title_ar: null,
    brand: null,
    image: offers[0]?.images[0] ?? null,
    supplier_count: offers.length,
    offer_count: offers.length,
    min_price: null,
    max_price: null,
    currency: "EGP",
    in_stock: true,
    last_verified_at: null,
    category: null,
    offers,
    ...extra,
  };
}

const NILE = offer("o-nile", "nile-parts", 385, { images: ["n1", "n2"] });
const VOLT = offer("o-volt", "volt-corner", 410, { images: ["v1"], ai: true });
const DELTA = offer("o-delta", "delta-bench", 425);
const OASIS = offer("o-oasis", "oasis-lab", 450, { images: ["o1"], ai: true });
const SINAI = offer("o-sinai", "sinai-spares", 300, { stock: "out_of_stock", images: ["s1"] });
const ALL = [OASIS, NILE, DELTA, VOLT, SINAI];

describe("matched by AI", () => {
  it("reads the offer's mark; an API without one means the rules", () => {
    expect(isAiMatched(VOLT)).toBe(true);
    expect(isAiMatched(NILE)).toBe(false);
    const older: Offer = { ...NILE };
    delete older.matched_by;
    expect(isAiMatched(older)).toBe(false);
  });

  it("counts from the API, else from the offers", () => {
    expect(aiMatchedCount(product(ALL))).toBe(2);
    expect(aiMatchedCount(product(ALL, { ai_matched_count: 3 }))).toBe(3);
    expect(aiMatchedCount(product([NILE, DELTA]))).toBe(0);
  });

  it("says how many, in the owner's words", () => {
    expect(aiNoteText(2, 5)).toBe("2 of 5 offers were matched automatically by AI.");
    expect(aiNoteText(1, 3)).toBe("1 of 3 offers was matched automatically by AI.");
  });
});

describe("picking on load", () => {
  it("opens on the product's representative, the listing its title comes from", () => {
    // Owner decision (November 2026): the h1 and <title> name one listing.
    // The API names it; Volt's is dearer than Nile's, and still picked.
    expect(initialPick(ALL, null, NOW, VOLT.id)).toEqual({ offer: VOLT, explicit: false });
  });

  it("?shop= picks that shop's lead offer, whatever the representative", () => {
    expect(initialPick(ALL, "volt-corner", NOW, NILE.id)).toEqual({ offer: VOLT, explicit: true });
    expect(initialPick(ALL, "sinai-spares", NOW, NILE.id)).toEqual({
      offer: SINAI,
      explicit: true,
    });
  });

  it("an unknown shop falls back to the representative", () => {
    expect(initialPick(ALL, "no-such-shop", NOW, VOLT.id)).toEqual({
      offer: VOLT,
      explicit: false,
    });
  });

  it("without a representative among the offers (an older API), the cheapest", () => {
    // Sinai is cheaper but out of stock: the primary offer is Nile's.
    expect(initialPick(ALL, null, NOW)).toEqual({ offer: NILE, explicit: false });
    expect(initialPick(ALL, null, NOW, "o-not-here")).toEqual({ offer: NILE, explicit: false });
  });

  it("a shop with several offers leads with its cheapest in stock", () => {
    const cheapGone = offer("o-n0", "nile-parts", 200, { stock: "out_of_stock" });
    const dear = offer("o-n2", "nile-parts", 500);
    expect(shopLead([dear, cheapGone, NILE], "nile-parts", NOW)).toBe(NILE);
    expect(shopLead([dear], "volt-corner", NOW)).toBeNull();
  });

  it("reads one ?shop= value", () => {
    expect(shopParam("volt-corner")).toBe("volt-corner");
    expect(shopParam(["volt-corner", "nile-parts"])).toBe("volt-corner");
    expect(shopParam("")).toBeNull();
    expect(shopParam(undefined)).toBeNull();
  });
});

describe("what follows a pick", () => {
  const photos = galleryPhotos(product([NILE, VOLT, DELTA, OASIS]));

  it("the gallery goes to the shop's first photo, or stays", () => {
    expect(photos.map((photo) => photo.src)).toEqual(["n1", "n2", "v1", "o1"]);
    expect(photoIndexOf(VOLT, ALL, photos)).toBe(2);
    expect(photoIndexOf(NILE, ALL, photos)).toBe(0);
    expect(photoIndexOf(DELTA, ALL, photos)).toBeNull();
  });

  it("an offer with no photo of its own borrows its shop's", () => {
    const second = offer("o-volt-2", "volt-corner", 420);
    expect(photoIndexOf(second, [...ALL, second], photos)).toBe(2);
  });

  it("the tab is the offer's own, else its shop's, else none", () => {
    const sources = detailSources(
      [NILE, VOLT, DELTA],
      new Map([
        ["o-nile", "A description long enough to count."],
        ["o-volt", "Another description, longer than the first one by a little."],
      ]),
    );
    expect(sources.map((source) => source.offer.id)).toEqual(["o-volt", "o-nile"]);
    expect(detailIndexOf(NILE, sources)).toBe(1);
    expect(detailIndexOf(VOLT, sources)).toBe(0);
    expect(detailIndexOf(DELTA, sources)).toBeNull();
    expect(detailIndexOf(offer("o-volt-2", "volt-corner", 1), sources)).toBe(0);
  });

  it("the URL gains ?shop=, keeping the rest", () => {
    expect(shopViewUrl("https://makhzan.test/products/p1?x=1#offers", "volt-corner")).toBe(
      "/products/p1?x=1&shop=volt-corner#offers",
    );
    expect(shopViewUrl("https://makhzan.test/products/p1?shop=nile-parts", "volt-corner")).toBe(
      "/products/p1?shop=volt-corner",
    );
    // No shop: the param goes, the rest stays.
    expect(shopViewUrl("https://makhzan.test/products/p1?shop=nile-parts&x=1#o", null)).toBe(
      "/products/p1?x=1#o",
    );
  });
});

describe("the report form, opened from the AI note", () => {
  const context = reportContextOf({
    productId: "p1",
    title: "Stepper driver",
    offers: ALL,
    category: null,
    page: "https://makhzan.test/products/p1",
    now: NOW,
  });

  it("marks the AI-matched offers", () => {
    expect(context.offers.filter((o) => o.ai).map((o) => o.id)).toEqual(["o-volt", "o-oasis"]);
  });

  it("lists them first, in the page's order otherwise, none ticked", () => {
    const form = { ...blankForm(), step: 2 as const, reason: "offers_not_same" as const };
    expect(offersToList(context, form).map((o) => o.id)).toEqual(context.offers.map((o) => o.id));
    const fromNote = { ...form, aiFirst: true };
    expect(offersToList(context, fromNote).map((o) => o.id)).toEqual([
      "o-volt",
      "o-oasis",
      "o-nile",
      "o-delta",
      "o-sinai",
    ]);
    expect(fromNote.offers).toEqual([]);
  });
});
