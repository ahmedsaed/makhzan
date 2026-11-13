/**
 * How offers are compared, and what travels with the price that wins.
 *
 * One module for the rules the product page applies in four places (the
 * summary, the offer rows, the primary button and the phone's bottom bar), so
 * the four can never disagree. Pure functions over `Offer`; the JSX only lays
 * out what these return. The rules are the owner-approved Phase 2 mockup's
 * (docs/DESIGN.md, "Product", and rule C3):
 *
 * - Offers are compared by the **price of one**, as every shop publishes it.
 *   An offer counts its lowest **in-stock** option: an option is a price the
 *   shop publishes for this listing. An out-of-stock option never sets it.
 * - Wherever a price of one comes from an offer with a minimum order, "each"
 *   and the minimum with its total stand beside it.
 * - An offer **on request** has no price to compare: it never enters the
 *   range, the button or the bar, and sorts after every priced offer.
 * - Quantity prices stay on their own row; the summary adds one line only when
 *   one beats every price of one.
 * - An out-of-date offer (C2b) counts nowhere while any fresh one exists.
 */
import type { Offer, PriceBreak, StockSignal, Variant } from "@/lib/api";
import { formatPrice, plural } from "@/lib/format";
import { isStaleCheck, parseVerified } from "@/lib/freshness";

// --------------------------------------------------------------------------- //
// Stock and age
// --------------------------------------------------------------------------- //

/** Low stock is still stock: the shop says it can sell one today. */
export function isInStock(signal: StockSignal): boolean {
  return signal === "in_stock" || signal === "low_stock";
}

export function isOutOfStock(offer: Offer): boolean {
  return offer.stock_signal === "out_of_stock";
}

export function checkedAt(offer: Offer): number {
  return parseVerified(offer.last_verified_at)?.getTime() ?? 0;
}

/** Last checked more than STALE_AFTER_DAYS ago (rule C2b). */
export function isStaleOffer(offer: Offer, now: Date = new Date()): boolean {
  return isStaleCheck(parseVerified(offer.last_verified_at), now);
}

/**
 * The offers the page leads with: the recently checked ones when there are
 * any, every offer when all of them are stale. A product whose every offer is
 * old still has a page (a direct link must work); it just says so (F2).
 */
export function preferFresh(offers: Offer[], now: Date = new Date()): Offer[] {
  const fresh = offers.filter((offer) => !isStaleOffer(offer, now));
  return fresh.length > 0 ? fresh : offers;
}

// --------------------------------------------------------------------------- //
// One offer's prices
// --------------------------------------------------------------------------- //

/** No price to compare: the shop gives it on request (or gives none). Never free. */
export function isOnRequest(offer: Offer): boolean {
  return offer.price === null;
}

/** An option the shop says is in stock. Unknown is not "yes": it never sets the lowest. */
function optionInStock(variant: Variant): boolean {
  return variant.in_stock === true;
}

/** The price of one this offer is compared by, and the option that gives it. */
export type UnitPrice = { price: number; option: string | null };

/**
 * The lowest price of one the offer has in stock: its listing price, or an
 * in-stock option's when that is lower (the option is then named wherever the
 * price leads). Null on request.
 */
export function unitPrice(offer: Offer): UnitPrice | null {
  if (offer.price === null) return null;
  let best: UnitPrice = { price: offer.price, option: null };
  for (const variant of offer.variants ?? []) {
    if (optionInStock(variant) && variant.price !== null && variant.price < best.price) {
      best = { price: variant.price, option: variant.title };
    }
  }
  return best;
}

export type Span = { min: number; max: number };

function spanOf(prices: number[]): Span | null {
  return prices.length ? { min: Math.min(...prices), max: Math.max(...prices) } : null;
}

/**
 * Every price a row shows: the listing's and each option's, in stock or not,
 * since the table inside the row gives each option's stock. Null on request.
 */
export function rowSpan(offer: Offer): Span | null {
  if (offer.price === null) return null;
  const options = (offer.variants ?? []).flatMap((v) => (v.price === null ? [] : [v.price]));
  return spanOf([offer.price, ...options]);
}

/**
 * The headline of a one-shop page: the listing's price and its in-stock
 * options' (C3: "EGP 1,700 – 1,750" when one colour costs more). When no
 * option is in stock, every option's, so the range still says what they cost.
 */
export function boxSpan(offer: Offer): Span | null {
  if (offer.price === null) return null;
  const variants = offer.variants ?? [];
  const inStock = variants.filter(optionInStock);
  const counted = inStock.length > 0 ? inStock : variants;
  const options = counted.flatMap((v) => (v.price === null ? [] : [v.price]));
  return spanOf([offer.price, ...options]);
}

// --------------------------------------------------------------------------- //
// Minimum order
// --------------------------------------------------------------------------- //

/**
 * The fewest the shop sells: its minimum, else its multiple (a shop that sells
 * only in tens sells at least ten). Null when it sells singly.
 */
export function minimumOrder(offer: Offer): number | null {
  const min = offer.min_quantity ?? null;
  const step = offer.multiple_of ?? null;
  const fewest = Math.max(min ?? 0, step ?? 0);
  return fewest > 1 ? fewest : null;
}

/** True when a price of one from this offer must say "each" (C3). */
export function needsEach(offer: Offer): boolean {
  return minimumOrder(offer) !== null;
}

/** "10 (EGP 1.50)": the minimum and what it costs at `price` each. */
export function minimumWithTotal(offer: Offer, price: number | null = offer.price): string | null {
  const fewest = minimumOrder(offer);
  if (fewest === null || price === null) return null;
  return `${fewest} (${formatPrice(roundMoney(price * fewest), offer.currency)})`;
}

/** "min. 10 (EGP 1.50)". */
export function minimumText(offer: Offer, price: number | null = offer.price): string | null {
  const text = minimumWithTotal(offer, price);
  return text && `min. ${text}`;
}

const STEP_WORDS: Record<number, string> = {
  2: "pairs",
  5: "fives",
  10: "tens",
  25: "twenty-fives",
  50: "fifties",
  100: "hundreds",
};

/**
 * "min. 10 (EGP 1.50), then in tens" for the one-shop box: the minimum, its
 * total, and how the quantity steps after it, when the shop says.
 */
export function minimumLine(offer: Offer): string | null {
  const text = minimumText(offer);
  if (!text) return null;
  const step = offer.multiple_of ?? null;
  const fewest = minimumOrder(offer);
  if (step === null || step <= 1) return text;
  if (step === fewest) return `${text}, then in ${STEP_WORDS[step] ?? `steps of ${step}`}`;
  return `${text}, in multiples of ${step}`;
}

/** Money to the piastre: 0.15 × 10 is 1.5, not 1.5000000000000002. */
function roundMoney(amount: number): number {
  return Math.round(amount * 100) / 100;
}

// --------------------------------------------------------------------------- //
// Quantity prices
// --------------------------------------------------------------------------- //

/** One row of "Price by quantity": `to` null is "or more". */
export type BreakRow = { from: number; to: number | null; price: number };

/**
 * The shop's quantity prices as rows, starting at its price of one (or its
 * minimum): 1–9 EGP 47, 10–49 EGP 44, 50 or more EGP 42. Empty with no breaks
 * or no price.
 */
export function priceBreakRows(offer: Offer): BreakRow[] {
  if (offer.price === null) return [];
  const start = minimumOrder(offer) ?? 1;
  const breaks = (offer.price_breaks ?? [])
    .filter((b) => b.min_quantity > start)
    .sort((a, b) => a.min_quantity - b.min_quantity);
  if (breaks.length === 0) return [];
  const steps: { from: number; price: number }[] = [
    { from: start, price: offer.price },
    ...breaks.map((b) => ({ from: b.min_quantity, price: b.price })),
  ];
  return steps.map((step, i) => ({
    from: step.from,
    to: i < steps.length - 1 ? steps[i + 1].from - 1 : null,
    price: step.price,
  }));
}

/** "1–9", "10", "50 or more". */
export function quantityLabel(row: BreakRow): string {
  if (row.to === null) return `${row.from} or more`;
  return row.to === row.from ? `${row.from}` : `${row.from}–${row.to}`;
}

/** "EGP 44 from 10, EGP 42 from 50": the row's short form. */
export function breaksText(offer: Offer): string | null {
  const breaks: PriceBreak[] = offer.price_breaks ?? [];
  if (offer.price === null || breaks.length === 0) return null;
  return breaks
    .map((b) => `${formatPrice(b.price, offer.currency)} from ${b.min_quantity}`)
    .join(", ");
}

// --------------------------------------------------------------------------- //
// Ordering
// --------------------------------------------------------------------------- //

/**
 * Lowest price of one first (`unitPrice`, so a cheaper in-stock option
 * counts). An offer on request goes after every priced one, since "Price on
 * request" must never sort as free, and equal prices put the more recently
 * checked offer first: it is the likelier to still be true.
 */
export function orderOffers(offers: Offer[]): Offer[] {
  return [...offers].sort((a, b) => {
    const pa = unitPrice(a)?.price ?? null;
    const pb = unitPrice(b)?.price ?? null;
    if (pa === null || pb === null) {
      if (pa !== pb) return pa === null ? 1 : -1;
    } else if (pa !== pb) {
      return pa - pb;
    }
    return checkedAt(b) - checkedAt(a);
  });
}

// --------------------------------------------------------------------------- //
// Several offers
// --------------------------------------------------------------------------- //

export type PricedOffer = { offer: Offer } & UnitPrice;

/** "Buying 100 or more? Shop lists EGP 35 each from 100." */
export type QuantityHint = { shop: string; quantity: number; price: number; currency: string };

/**
 * What the summary, the facts line, the primary button and the bottom bar are
 * built on.
 *
 * `state`: `in_stock` when any shop says it has stock; `unconfirmed` when none
 * says so but some do not say it is gone (an "unknown" signal is not a "no");
 * `out_of_stock` when every shop says it is. The offers in that state are the
 * counted ones; of those, `priced` are compared by the price of one (lowest
 * first) and `onRequest` are listed after them, most recently checked first.
 */
export type Comparison = {
  state: "in_stock" | "unconfirmed" | "out_of_stock";
  /** Priced offers counted, or, with none priced, the offers on request. */
  offerCount: number;
  shopCount: number;
  priced: PricedOffer[];
  onRequest: Offer[];
  /** The range of prices of one, over `priced`; null when nothing is priced. */
  min: number | null;
  max: number | null;
  /** Any priced offer has a minimum: the range reads "each". */
  each: boolean;
  /** The cheapest priced offer: what the button and the bar lead with. */
  best: PricedOffer | null;
  hint: QuantityHint | null;
};

function shopKey(offer: Offer): string {
  return offer.supplier?.slug ?? offer.id;
}

function shopsIn(offers: Offer[]): number {
  return new Set(offers.map(shopKey)).size;
}

/**
 * Counted over the recently checked offers when there are any (C2b), so the
 * summary and the offers above the folds agree; over every offer when all are
 * stale, and the page says so.
 */
export function compareOffers(all: Offer[], now: Date = new Date()): Comparison {
  const offers = preferFresh(all, now);
  const inStock = offers.filter((offer) => isInStock(offer.stock_signal));
  const notGone = offers.filter((offer) => !isOutOfStock(offer));
  const [state, counted]: [Comparison["state"], Offer[]] =
    inStock.length > 0
      ? ["in_stock", inStock]
      : notGone.length > 0
        ? ["unconfirmed", notGone]
        : ["out_of_stock", offers];

  const priced = orderOffers(counted).flatMap((offer) => {
    const unit = unitPrice(offer);
    return unit ? [{ offer, ...unit }] : [];
  });
  const onRequest = counted.filter(isOnRequest).sort((a, b) => checkedAt(b) - checkedAt(a));
  const shown = priced.length > 0 ? priced.map((p) => p.offer) : onRequest;
  const min = priced.length ? priced[0].price : null;
  const max = priced.length ? Math.max(...priced.map((p) => p.price)) : null;

  let hint: QuantityHint | null = null;
  if (state === "in_stock" && min !== null) {
    for (const { offer } of priced) {
      for (const b of offer.price_breaks ?? []) {
        if (b.price < min && (!hint || b.price < hint.price)) {
          hint = {
            shop: offer.supplier?.name ?? "A shop",
            quantity: b.min_quantity,
            price: b.price,
            currency: offer.currency,
          };
        }
      }
    }
  }

  return {
    state,
    offerCount: shown.length,
    shopCount: shopsIn(shown),
    priced,
    onRequest,
    min,
    max,
    each: priced.some((p) => needsEach(p.offer)),
    best: priced[0] ?? null,
    hint,
  };
}

/**
 * "2 offers in stock at 2 shops · 1 more on request", "2 offers in stock at 2
 * shops, prices on request", "1 offer at 1 shop, stock not confirmed", "Out of
 * stock at all 3 shops".
 */
export function comparisonText(comparison: Comparison): string {
  const { offerCount, shopCount, priced, onRequest } = comparison;
  const counts = `${plural(offerCount, "offer")}`;
  const shops = plural(shopCount, "shop");
  if (comparison.state === "out_of_stock") {
    return shopCount === 1 ? "Out of stock" : `Out of stock at all ${shopCount} shops`;
  }
  const where = comparison.state === "in_stock" ? `in stock at ${shops}` : `at ${shops}`;
  const unconfirmed = comparison.state === "unconfirmed" ? ", stock not confirmed" : "";
  if (priced.length === 0 && onRequest.length > 0) {
    return `${counts} ${where}${unconfirmed}, prices on request`;
  }
  const more = onRequest.length > 0 ? ` · ${onRequest.length} more on request` : "";
  return `${counts} ${where}${unconfirmed}${more}`;
}

/**
 * The notes that travel with a leading price wherever it appears (the button,
 * the bottom bar): its minimum with the total, the option it is, and whether
 * it ships from abroad. "min. 10 (EGP 1.50) · “Without headers” option".
 */
export function leadNotes(lead: PricedOffer): string[] {
  const notes: string[] = [];
  const minimum = minimumText(lead.offer, lead.price);
  if (minimum) notes.push(minimum);
  if (lead.option) notes.push(`“${lead.option}” option`);
  if (lead.offer.ships_from_abroad) notes.push("ships from abroad");
  return notes;
}

/** "EGP 0.15 each" for an offer with a minimum, else "EGP 320". */
export function unitPriceText(lead: PricedOffer): string {
  const price = formatPrice(lead.price, lead.offer.currency);
  return needsEach(lead.offer) ? `${price} each` : price;
}

// --------------------------------------------------------------------------- //
// Options
// --------------------------------------------------------------------------- //

/** Rows the options table shows before "Show N more options". */
export const OPTIONS_SHOWN = 6;

/** "6 of 8 in stock". */
export function optionsInStock(offer: Offer): number {
  return (offer.variants ?? []).filter(optionInStock).length;
}

// --------------------------------------------------------------------------- //
// What a part fits
// --------------------------------------------------------------------------- //

/** Up to this many models are named in the pill itself; more fold. */
export const FITS_INLINE = 2;

/**
 * "Fits K2 Plus" or "Fits Ender 3, Anet A8" inline; more than two fold behind
 * "Fits 4 models". A shop's claim about its own listing: never merged across
 * offers.
 */
export function fitsLabel(models: string[]): string | null {
  if (models.length === 0) return null;
  return models.length <= FITS_INLINE
    ? `Fits ${models.join(", ")}`
    : `Fits ${plural(models.length, "model")}`;
}

// --------------------------------------------------------------------------- //
// Manufacturer part numbers
// --------------------------------------------------------------------------- //

/** Case and spacing folded, so "ne 555" and "NE555" are one number. */
function foldPart(value: string): string {
  return value.replace(/\s+/g, "").toUpperCase();
}

/** "A", "A and B", "A, B and C". */
export function joinNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * What the title block says about part numbers, beyond makhzan's own.
 *
 * - `alsoStatedBy`: shops stating makhzan's own part number ("· also stated by").
 * - `stated`: one number the shops state, different from makhzan's own, with
 *   who states it ("Mfr. part number X · from A's listing").
 * - `disagree`: two or more different numbers ("Shops state 2 manufacturer
 *   part numbers: …"); then none of them stands under the title on its own,
 *   and each offer row shows its own.
 */
export type PartNumbers = {
  alsoStatedBy: string[];
  stated: { value: string; shops: string[] } | null;
  disagree: string[] | null;
};

export function partNumbers(partNumber: string | null, offers: Offer[]): PartNumbers {
  const values = new Map<string, { value: string; shops: string[] }>();
  for (const offer of offers) {
    const value = offer.mfr_part_number?.trim();
    if (!value) continue;
    const key = foldPart(value);
    const entry = values.get(key) ?? { value, shops: [] };
    const shop = offer.supplier?.name ?? "a shop";
    if (!entry.shops.includes(shop)) entry.shops.push(shop);
    values.set(key, entry);
  }
  const own = partNumber ? foldPart(partNumber) : null;
  const alsoStatedBy = own ? (values.get(own)?.shops ?? []) : [];
  const all = [...values.values()];
  if (all.length > 1) return { alsoStatedBy, stated: null, disagree: all.map((v) => v.value) };
  const only = all[0];
  return {
    alsoStatedBy,
    stated: only && foldPart(only.value) !== own ? only : null,
    disagree: null,
  };
}

/** "Cairo Makers's listing" or "A's and B's listings". */
export function listingsOf(shops: string[]): string {
  return shops.length === 1
    ? `${shops[0]}'s listing`
    : `${joinNames(shops.map((s) => `${s}'s`))} listings`;
}
