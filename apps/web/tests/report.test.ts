/**
 * "Report a problem": the form's rules, without a browser (lib/report.ts).
 * Fictional shops throughout.
 */
import { describe, expect, it, vi } from "vitest";

import type { Offer } from "@/lib/api";
import {
  blankForm,
  buildPayload,
  candidateMeta,
  emailFallback,
  type FormState,
  limitedTitle,
  priceValue,
  productIdFromLink,
  reasonsFor,
  reportContextOf,
  type ReportContext,
  submitReport,
  validate,
  waitText,
} from "@/lib/report";

const NOW = new Date("2026-11-13T12:00:00Z");
const PRODUCT = "6f1c2a9e-3b7d-4c51-9a0e-2d8f61b4c7a3";

function offer(id: string, shop: string, extra: Partial<Offer> = {}): Offer {
  return {
    id,
    title_en: `TB6600 at ${shop}`,
    title_ar: null,
    price: 425,
    currency: "EGP",
    stock_signal: "in_stock",
    source_url: `https://${shop}.test/p`,
    images: [],
    last_verified_at: "2026-11-10T10:00:00Z",
    supplier: { id: shop, slug: shop, name: shop.replace(/-/g, " "), name_ar: null } as never,
    ...extra,
  } as Offer;
}

const TWO: ReportContext = {
  productId: PRODUCT,
  title: "TB6600 Stepper Motor Driver 4A",
  category: "Electronic components › Motor control › Stepper drivers",
  page: `https://makhzan.test/products/${PRODUCT}`,
  offers: [
    {
      id: "o-delta",
      title: "TB6600 Stepper Motor Driver 4A 9-42V",
      shop: { slug: "delta-components", name: "Delta Components" },
      price: "EGP 425",
      outOfStock: false,
      stale: false,
    },
    {
      id: "o-giza",
      title: "TB6600 4A Stepper Driver Module",
      shop: { slug: "giza-robotics", name: "Giza Robotics" },
      price: "EGP 504",
      outOfStock: true,
      stale: false,
    },
    {
      id: "o-giza-2",
      title: "TB6600 (upgraded)",
      shop: { slug: "giza-robotics", name: "Giza Robotics" },
      price: "EGP 550",
      outOfStock: false,
      stale: true,
    },
  ],
};

const ONE: ReportContext = { ...TWO, offers: [TWO.offers[0]] };

const step2 = (change: Partial<FormState>): FormState => ({ ...blankForm(), step: 2, ...change });

describe("reasons", () => {
  it("offers comparing offers only where there are several", () => {
    expect(reasonsFor(TWO).map((r) => r.key)).toEqual([
      "offers_not_same",
      "same_as_other",
      "wrong_price_stock",
      "wrong_category",
      "wrong_details",
      "shop_contact",
      "other",
    ]);
    expect(reasonsFor(ONE).map((r) => r.key)).not.toContain("offers_not_same");
  });
});

describe("validate", () => {
  it("needs a reason to continue", () => {
    expect(validate(blankForm(), TWO)).toEqual({ reason: "Choose what’s wrong to continue." });
    expect(validate({ ...blankForm(), reason: "other" }, TWO)).toEqual({});
  });

  it.each([
    [{ reason: "offers_not_same" }, "offers"],
    [{ reason: "same_as_other" }, "other"],
    [{ reason: "wrong_price_stock", field: "price" }, "priceOffer"],
    [{ reason: "wrong_price_stock", priceOffer: "o-delta" }, "field"],
    [{ reason: "wrong_details" }, "detailField"],
    [{ reason: "shop_contact", contactField: "phone" }, "contactShop"],
    [{ reason: "shop_contact", contactShop: "giza-robotics" }, "contactField"],
    [{ reason: "other", description: "bad" }, "description"],
  ] as [Partial<FormState>, string][])("%o needs %s", (change, key) => {
    expect(Object.keys(validate(step2(change), TWO))).toEqual([key]);
  });

  it("asks one shop's page nothing it already knows", () => {
    expect(validate(step2({ reason: "wrong_price_stock", field: "stock" }), ONE)).toEqual({});
    expect(validate(step2({ reason: "shop_contact", contactField: "hours" }), ONE)).toEqual({});
  });

  it("takes an email only when it looks complete", () => {
    const base = { reason: "wrong_category" } as const;
    expect(validate(step2({ ...base, email: "buyer@example" }), TWO).email).toMatch(/complete/);
    expect(validate(step2({ ...base, email: " buyer@example.com " }), TWO)).toEqual({});
    expect(validate(step2({ ...base, email: "" }), TWO)).toEqual({});
  });

  it("stops at 1,000 characters", () => {
    expect(
      validate(step2({ reason: "wrong_category", description: "x".repeat(1001) }), TWO).description,
    ).toMatch(/1,000/);
  });
});

describe("buildPayload", () => {
  it("sends the offers ticked as different", () => {
    const payload = buildPayload(
      step2({ reason: "offers_not_same", offers: ["o-giza"], description: "  smaller  " }),
      TWO,
      8123.4,
    );
    expect(payload).toEqual({
      product_id: PRODUCT,
      reason: "offers_not_same",
      offer_ids: ["o-giza"],
      other_product_id: null,
      field: null,
      correct_value: null,
      description: "smaller",
      email: null,
      website: "",
      elapsed_ms: 8123,
    });
  });

  it("sends a price as the shop shows it, and a stock as one of three words", () => {
    const price = buildPayload(
      step2({ reason: "wrong_price_stock", priceOffer: "o-delta", field: "price", value: "1200" }),
      TWO,
      5000,
    );
    expect([price.offer_ids, price.field, price.correct_value]).toEqual([
      ["o-delta"],
      "price",
      "EGP 1,200",
    ]);
    const stock = buildPayload(
      step2({ reason: "wrong_price_stock", field: "stock", stockValue: "gone" }),
      ONE,
      5000,
    );
    expect([stock.offer_ids, stock.correct_value]).toEqual([["o-delta"], "gone"]);
  });

  it("names every offer of the shop whose details are wrong", () => {
    const contact = buildPayload(
      step2({ reason: "shop_contact", contactShop: "giza-robotics", contactField: "hours" }),
      TWO,
      5000,
    );
    expect([contact.offer_ids, contact.field]).toEqual([["o-giza", "o-giza-2"], "hours"]);
    const details = buildPayload(step2({ reason: "wrong_details", detailField: "photo" }), TWO, 1);
    expect(details.offer_ids).toEqual([]);
    const sole = buildPayload(step2({ reason: "wrong_details", detailField: "photo" }), ONE, 1);
    expect(sole.offer_ids).toEqual(["o-delta"]);
  });

  it("drops what the chosen reason does not take", () => {
    const payload = buildPayload(
      step2({
        reason: "wrong_category",
        offers: ["o-giza"],
        priceOffer: "o-delta",
        category: " Motor drivers ",
        other: { id: "x", title: "x", meta: "" },
      }),
      TWO,
      1,
    );
    expect(payload.offer_ids).toEqual([]);
    expect(payload.other_product_id).toBeNull();
    expect([payload.field, payload.correct_value]).toEqual(["category", "Motor drivers"]);
  });

  it("carries the honeypot as it was", () => {
    expect(buildPayload(step2({ reason: "other", website: "x" }), TWO, 1).website).toBe("x");
  });
});

describe("priceValue", () => {
  it.each([
    ["460", "EGP 460"],
    ["EGP 1,200.5", "EGP 1,200.5"],
    [" 99.99 ", "EGP 99.99"],
    ["about 400", null],
    ["", null],
  ])("%s → %s", (typed, expected) => {
    expect(priceValue(typed)).toBe(expected);
  });
});

describe("productIdFromLink", () => {
  it("reads a product link, a bare id, and nothing else", () => {
    expect(
      productIdFromLink(`https://makhzan.merope.dev/products/${PRODUCT}-tb6600-driver?x=1`),
    ).toBe(PRODUCT);
    expect(productIdFromLink(PRODUCT.toUpperCase())).toBe(PRODUCT);
    expect(productIdFromLink("TB6600")).toBeNull();
  });
});

describe("candidateMeta", () => {
  it("says who sells it and for how much", () => {
    expect(candidateMeta(3, "EGP 900 – 990")).toBe("3 shops · EGP 900 – 990");
    expect(candidateMeta(1, "EGP 390", "Nile Parts")).toBe("Sold by Nile Parts · EGP 390");
    expect(candidateMeta(1, null)).toBe("Sold by 1 shop");
  });
});

describe("too many reports", () => {
  it("says how many, and how long to wait", () => {
    expect(limitedTitle({ limit: "hour", count: 5, minutes: 40 })).toBe(
      "You’ve sent 5 reports in the last hour.",
    );
    expect(limitedTitle({ limit: "day", count: 20, minutes: 300 })).toMatch(/20 reports/);
    expect(waitText(40)).toBe("about 40 minutes");
    expect(waitText(1)).toBe("about 1 minute");
    expect(waitText(300)).toBe("about 5 hours");
  });
});

describe("submitReport", () => {
  const payload = buildPayload(step2({ reason: "wrong_category" }), TWO, 5000);
  const reply = (status: number, body: unknown, headers: Record<string, string> = {}) =>
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json", ...headers },
      }),
    );

  it("posts to the API through the web app's own origin", async () => {
    const fetcher = reply(202, { reference: "R-12" });
    expect(await submitReport(payload, fetcher)).toEqual({ kind: "sent", reference: "R-12" });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("/api/reports");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(payload);
  });

  it("reads the limit the API gives", async () => {
    const fetcher = reply(
      429,
      { detail: { limit: "hour", count: 5, retry_after_minutes: 40 } },
      { "retry-after": "2400" },
    );
    expect(await submitReport(payload, fetcher)).toEqual({
      kind: "limited",
      limit: "hour",
      count: 5,
      minutes: 40,
    });
  });

  it("never throws", async () => {
    expect(await submitReport(payload, reply(500, {}))).toEqual({ kind: "error" });
    expect(
      await submitReport(payload, vi.fn().mockRejectedValue(new TypeError("offline"))),
    ).toEqual({ kind: "error" });
  });

  it("treats a report the API kept quiet about as sent", async () => {
    expect(await submitReport(payload, reply(202, { reference: null }))).toEqual({
      kind: "sent",
      reference: null,
    });
  });
});

describe("the email fallback", () => {
  it("carries what was written and the page", () => {
    const href = decodeURIComponent(
      emailFallback(step2({ reason: "wrong_category", description: "Not a sensor" }), TWO),
    );
    expect(href).toMatch(/^mailto:crawler@makhzan\.merope\.dev\?subject=Report a problem: TB6600/);
    expect(href).toContain("Not a sensor");
    expect(href).toContain(`Page: https://makhzan.test/products/${PRODUCT}`);
  });
});

describe("reportContextOf", () => {
  it("lists every offer, folded ones after, each with its own title and price", () => {
    const context = reportContextOf({
      productId: PRODUCT,
      title: "TB6600",
      category: null,
      page: "https://makhzan.test/p",
      now: NOW,
      offers: [
        offer("old", "nile-parts", { last_verified_at: "2026-08-01T00:00:00Z", price: 300 }),
        offer("gone", "giza-robotics", { stock_signal: "out_of_stock", price: 400 }),
        offer("live", "delta-components", { price: 425 }),
        offer("ask", "cairo-makers", { price: null, price_on_request: true }),
      ],
    });
    expect(context.offers.map((o) => [o.id, o.price, o.outOfStock, o.stale])).toEqual([
      ["live", "EGP 425", false, false],
      ["ask", "Price on request", false, false],
      ["gone", "EGP 400", true, false],
      ["old", "EGP 300", false, true],
    ]);
    expect(context.offers[0].shop).toEqual({ slug: "delta-components", name: "delta components" });
  });
});
