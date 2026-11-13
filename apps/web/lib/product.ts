/**
 * The decisions behind the product page, as plain functions: which offers are
 * listed and in what order, what the summary says, which shop the primary
 * button opens, and what search engines are told. Kept out of the JSX so each
 * one is tested on its own.
 */
import type { Crumb } from "@/components/breadcrumb";
import type { Category, CategoryRef, Offer, Product } from "@/lib/api";
import {
  boxSpan,
  checkedAt,
  compareOffers,
  comparisonText,
  isInStock,
  isOutOfStock,
  isStaleOffer,
  minimumOrder,
  needsEach,
  orderOffers,
  partNumbers,
  preferFresh,
  type Comparison,
} from "@/lib/offers";
import { routes } from "@/lib/routes";
import { departmentLabel } from "@/lib/departments";

export {
  checkedAt,
  isInStock,
  isOutOfStock,
  isStaleOffer,
  orderOffers,
  preferFresh,
} from "@/lib/offers";

/**
 * The offers list, with the out-of-stock offers (rule C2) and the out-of-date
 * ones (C2b) each folded beneath it.
 *
 * A stale offer goes in the out-of-date fold whatever its stock: a months-old
 * "in stock" is no more reliable than its price. The out-of-stock fold then
 * holds the recently checked offers that say they are gone.
 *
 * A fold is never the whole list: when every offer is stale, or every one left
 * is out of stock, nothing is folded, since a fold holding everything would
 * leave a page that says nothing, and the reader came to see them.
 */
export function splitOffers(
  offers: Offer[],
  now: Date = new Date(),
): {
  listed: Offer[];
  outOfStock: Offer[];
  stale: Offer[];
} {
  const ordered = orderOffers(offers, now);
  const fresh = preferFresh(ordered, now);
  const stale = fresh === ordered ? [] : ordered.filter((offer) => isStaleOffer(offer, now));
  const outOfStock = fresh.filter(isOutOfStock);
  if (outOfStock.length === fresh.length) return { listed: fresh, outOfStock: [], stale };
  return { listed: fresh.filter((offer) => !isOutOfStock(offer)), outOfStock, stale };
}

/** What the summary above the offers counts: `compareOffers` (lib/offers.ts). */
export type OfferSummary = Comparison;

function shopsIn(offers: Offer[]): number {
  return new Set(offers.map((offer) => offer.supplier?.slug ?? offer.id)).size;
}

/** The comparison the summary, facts, button and bottom bar share (lib/offers.ts). */
export function summarizeOffers(all: Offer[], now: Date = new Date()): OfferSummary {
  return compareOffers(all, now);
}

/** "5 offers in stock at 3 shops". */
export function summaryText(summary: OfferSummary): string {
  return comparisonText(summary);
}

/**
 * The offer the primary button opens: the cheapest in stock; failing that the
 * cheapest not known to be gone; and when every shop is out of stock, the most
 * recently checked, since it is the one most likely to have restocked. Only an
 * offer with somewhere to go qualifies, and a recently checked one is preferred
 * to any stale one (C2b): a months-old price is not the one to lead with.
 */
export function primaryOffer(offers: Offer[], now: Date = new Date()): Offer | null {
  const linkable = preferFresh(
    orderOffers(offers, now).filter((offer) => offer.source_url && offer.supplier),
    now,
  );
  return (
    linkable.find((offer) => isInStock(offer.stock_signal)) ??
    linkable.find((offer) => !isOutOfStock(offer)) ??
    [...linkable].sort((a, b) => checkedAt(b) - checkedAt(a))[0] ??
    null
  );
}

/** Most a product page shows; a shop that posts 30 angles of a resistor is
 *  not helping anyone choose it. */
const MAX_PHOTOS = 8;

/** A photo and the name of the shop it comes from, for the badge on it. */
export type GalleryPhoto = { src: string; shop: string | null };

/**
 * The product's own photo first, then every offer's, each once, each with its
 * shop: the offer it came from, so a gallery of three shops' photos badges
 * each with its own. The product's photo is credited to the offer that lists
 * it, and failing that (no such offer: a withdrawn product) to `image_shop`.
 */
export function galleryPhotos(product: Product): GalleryPhoto[] {
  const shops = new Map<string, string | null>();
  for (const offer of product.offers) {
    for (const src of offer.images) {
      if (src && !shops.has(src)) shops.set(src, offer.supplier?.name ?? null);
    }
  }
  const all = [product.image, ...product.offers.flatMap((offer) => offer.images)];
  const unique = [...new Set(all.filter((src): src is string => Boolean(src)))];
  return unique.slice(0, MAX_PHOTOS).map((src) => ({
    src,
    shop: shops.get(src) ?? (src === product.image ? (product.image_shop?.name ?? null) : null),
  }));
}

/** "SG90 Servo" for the first photo, "SG90 Servo, photo 2" after it. The shop
 *  is added by the frame ("… — photo from Shop A", PhotoFrame). */
export function photoNumbered(alt: string, index: number): string {
  return index === 0 ? alt : `${alt}, photo ${index + 1}`;
}

/** The gallery's photo URLs alone: structured data, the share image. */
export function galleryImages(product: Product): string[] {
  return galleryPhotos(product).map((photo) => photo.src);
}

// --------------------------------------------------------------------------- //
// What the shop published: brand, specs, datasheets
// --------------------------------------------------------------------------- //

/**
 * The offer the page leads with: the one the primary button and the bottom
 * bar open, or the first offer when none of them can be opened. Its shop's
 * description, specs and datasheets are the ones shown.
 */
export function leadOffer(offers: Offer[]): Offer | null {
  return primaryOffer(offers) ?? offers[0] ?? null;
}

/** The brand, when known: the product's own, failing that the lead shop's. */
export function brandOf(product: Product): string | null {
  return product.brand || leadOffer(product.offers)?.brand || null;
}

export type SpecRow = { name: string; value: string; identifier: boolean };
export type DatasheetLink = { url: string; label: string };
/** A video the shop links from its listing: "UT61E review on YouTube". */
export type VideoLink = { url: string; label: string; host: string };

export type ShopDetails = {
  offer: Offer;
  /** "Shop A", for "From Shop A's listing". */
  shopName: string;
  specs: SpecRow[];
  datasheets: DatasheetLink[];
  videos: VideoLink[];
};

/** Names a shop gives the row that holds a part number. */
const PART_NUMBER_NAME =
  /^(?:manufacturer\s+)?(?:part(?:\s*(?:number|no\.?|#))?|model(?:\s*(?:number|no\.?|#))?|mpn|p\/n)$/i;
/** …and what a part number looks like: one token, letters and digits. */
const PART_NUMBER_VALUE = /^(?=.*\d)(?=.*[a-z])[a-z0-9][a-z0-9\-_./+#]{1,39}$/i;

/** True when a spec row is a part number, to be set in the monospace face (S3). */
export function isPartNumberSpec(name: string, value: string): boolean {
  return PART_NUMBER_NAME.test(name.trim()) && PART_NUMBER_VALUE.test(value.trim());
}

/** A datasheet's label: the shop's link text, else the file's name. */
export function datasheetLabel(url: string, label: string | null | undefined): string {
  if (label?.trim()) return label.trim();
  try {
    const file = new URL(url).pathname.split("/").filter(Boolean).pop();
    if (file) return decodeURIComponent(file);
  } catch {
    // Not a URL we can read a name from.
  }
  return "Datasheet";
}

/** Where a video is hosted, by name: "YouTube", "Vimeo", "Facebook", else the host. */
export function videoHost(url: string): string {
  let host: string;
  try {
    host = new URL(url).hostname.replace(/^(www|m)\./, "").toLowerCase();
  } catch {
    return "the web";
  }
  if (host === "youtu.be" || host === "youtube.com" || host.endsWith(".youtube.com")) {
    return "YouTube";
  }
  if (host === "vimeo.com" || host.endsWith(".vimeo.com")) return "Vimeo";
  if (host === "facebook.com" || host === "fb.watch" || host.endsWith(".facebook.com")) {
    return "Facebook";
  }
  if (host === "instagram.com") return "Instagram";
  if (host === "tiktok.com") return "TikTok";
  return host;
}

/**
 * The specs and datasheets to show, from the lead offer only (rule C4): never
 * merged across shops, so every row has one source the page can name. Null
 * when that shop published neither, and the page shows no section at all.
 */
export function shopDetails(product: Product): ShopDetails | null {
  const offer = leadOffer(product.offers);
  return offer ? offerDetails(offer) : null;
}

/** One offer's specs, datasheets and videos, or null when its shop published none. */
export function offerDetails(offer: Offer): ShopDetails | null {
  const specs = Object.entries(offer.specs ?? {})
    .filter(([name, value]) => name.trim() && typeof value === "string" && value.trim())
    .map(([name, value]) => ({ name, value, identifier: isPartNumberSpec(name, value) }));
  const datasheets = (offer.documents ?? [])
    .filter((doc) => /^https?:\/\//i.test(doc.url))
    .map((doc) => ({ url: doc.url, label: datasheetLabel(doc.url, doc.label) }));
  const videos = (offer.videos ?? [])
    .filter((video) => /^https:\/\//i.test(video.url))
    .map((video) => ({
      url: video.url,
      label: video.label?.trim() || "Video",
      host: videoHost(video.url),
    }));
  if (specs.length === 0 && datasheets.length === 0 && videos.length === 0) return null;
  return { offer, shopName: offer.supplier?.name ?? "the shop", specs, datasheets, videos };
}

/** What one shop wrote about a product: the "From:" tabs on the product page. */
export type DetailSource = {
  offer: Offer;
  /** The tab: the shop's name, numbered when one shop has several offers. */
  label: string;
  description: string | null;
  details: ShopDetails | null;
};

/** Most "From:" tabs; more than this many shops describing one part is unheard of. */
export const MAX_DETAIL_SOURCES = 8;

/**
 * Every offer whose shop wrote something (a description, specs, datasheets or videos),
 * richest first, so the page opens on the most informative one. Offers whose
 * shop wrote nothing get no tab: an empty tab is an empty section (rule C4).
 * Ties keep the offers' own order, cheapest in stock first.
 */
export function detailSources(
  offers: Offer[],
  descriptions: ReadonlyMap<string, string | null>,
): DetailSource[] {
  const ordered = orderOffers(offers);
  const sources = ordered
    .map((offer, index) => {
      const description = descriptions.get(offer.id)?.trim() || null;
      const details = offerDetails(offer);
      const score =
        (description ? 2 + Math.min(description.length, 1500) / 300 : 0) +
        (details?.specs.length ?? 0) +
        3 * (details?.datasheets.length ?? 0) +
        2 * (details?.videos.length ?? 0);
      return { offer, description, details, score, index };
    })
    .filter((source) => source.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .slice(0, MAX_DETAIL_SOURCES);

  const names = sources.map((source) => source.offer.supplier?.name ?? "Unknown shop");
  const seen = new Map<string, number>();
  return sources.map(({ offer, description, details }, i) => {
    const name = names[i];
    const count = (seen.get(name) ?? 0) + 1;
    seen.set(name, count);
    const repeated = names.filter((n) => n === name).length > 1;
    return { offer, description, details, label: repeated ? `${name} (${count})` : name };
  });
}

/**
 * Department › group › category, walked up the category's parents. Every crumb is a
 * link: on a product page none of them is the current page.
 */
export function categoryTrail(category: CategoryRef, categories: Category[]): Crumb[] {
  const byRef = new Map(categories.map((item) => [item.ref, item]));
  const chain: CategoryRef[] = [];
  let current: CategoryRef | undefined = byRef.get(category.ref) ?? category;
  const seen = new Set<string>();
  while (current && !seen.has(current.ref)) {
    seen.add(current.ref);
    chain.unshift(current);
    const parent: string | null | undefined = byRef.get(current.ref)?.parent;
    current = parent ? byRef.get(parent) : undefined;
  }
  return [
    { label: departmentLabel(category.domain), href: routes.department(category.domain) },
    ...chain.map((item) => ({
      label: item.name_en,
      href: routes.category(item.ref),
    })),
  ];
}

// --------------------------------------------------------------------------- //
// Structured data
// --------------------------------------------------------------------------- //

const SCHEMA = "https://schema.org/";

/** Longest description we put in structured data; the page has the rest. */
const JSON_LD_DESCRIPTION = 500;

/** Most spec rows marked up: the table on the page has the rest. */
export const JSON_LD_SPECS = 20;

/** Most models named as what a part fits. */
export const JSON_LD_FITS = 20;

/** Longest spec value marked up. */
const JSON_LD_SPEC_VALUE = 200;

/**
 * The price the page shows in its headline, and what it is counted over: the
 * numbers the structured data must repeat exactly (Google's structured data
 * policies: "don't mark up content that is not visible to readers of the
 * page", developers.google.com/search/docs/appearance/structured-data/sd-policies).
 *
 * - Two or more offers: the summary's range (`compareOffers`): the price of
 *   one over the counted offers (fresh first, C2b; in stock first), on-request
 *   offers left out.
 * - One offer: its box. With a minimum order, the price of one alone ("EGP
 *   0.15 each"); without, `boxSpan`, widened by its current in-stock options.
 *
 * Null when the page shows no price at all (on request only, or no price),
 * when every offer is out of date (C2b: the page warns its prices may have
 * changed, and markup cannot carry that warning), and for a withdrawn product.
 */
export type ShownPrice = {
  min: number;
  max: number;
  /** How many offers the range is over: the summary's count. */
  offerCount: number;
  /** The fewest anyone in the range sells: over 1 only when every one has a minimum. */
  fewest: number;
  availability: string | null;
};

export function shownPrice(product: Product, now: Date = new Date()): ShownPrice | null {
  if (product.status === "delisted" || product.offers.length === 0) return null;
  if (product.offers.every((offer) => isStaleOffer(offer, now))) return null;
  const comparison = compareOffers(product.offers, now);
  if (comparison.min === null || comparison.max === null) return null;
  let { min, max } = comparison;
  if (product.offers.length === 1) {
    const [only] = product.offers;
    const span = needsEach(only) ? null : boxSpan(only, now);
    if (span) ({ min, max } = span);
  }
  return {
    min,
    max,
    offerCount: comparison.offerCount,
    fewest: Math.min(...comparison.priced.map((p) => minimumOrder(p.offer) ?? 1)),
    availability: availabilityOf(comparison),
  };
}

/**
 * The availability the summary states, as schema.org's ItemAvailability:
 * in stock when a shop says so (limited when every one says low stock), out
 * of stock when every shop does, made to order when every counted offer is.
 * "Stock not confirmed" has no schema.org value, and none is claimed.
 */
function availabilityOf(comparison: Comparison): string | null {
  const signals = comparison.priced.map((p) => p.offer.stock_signal);
  if (comparison.state === "in_stock") {
    return signals.includes("in_stock") ? `${SCHEMA}InStock` : `${SCHEMA}LimitedAvailability`;
  }
  if (comparison.state === "out_of_stock") return `${SCHEMA}OutOfStock`;
  return signals.length > 0 && signals.every((s) => s === "made_to_order")
    ? `${SCHEMA}MadeToOrder`
    : null;
}

/**
 * What one shop says a part fits, when exactly one offer says anything: the
 * page shows "Fits …" per offer and never merges two shops' claims, so
 * neither does the markup. Null when no offer states it, or more than one.
 */
export function fitsClaim(offers: Offer[]): string[] | null {
  const claims = offers
    .map((offer) => (offer.compatible_with ?? []).map((m) => m.trim()).filter(Boolean))
    .filter((models) => models.length > 0);
  return claims.length === 1 ? [...new Set(claims[0])] : null;
}

export type ProductJsonLdOptions = {
  /** The description the page leads with (the richest shop's, else the summary). */
  description?: string | null;
  /** The shop the page's "What the shops say" opens on: its specs are marked up. */
  details?: ShopDetails | null;
  now?: Date;
};

/**
 * schema.org Product for search engines, marked up as what the page is: a
 * comparison of other shops' offers, not a shop selling the product.
 *
 * Always an AggregateOffer (low and high price, how many offers, whether any
 * is in stock), never an Offer, even for one shop. Google reads a page with an
 * Offer as a merchant selling the product there (a "merchant listing") and
 * then asks for what only a seller has: shipping, a return policy, a GTIN.
 * Google's product snippet guidance documents AggregateOffer for pages that
 * aggregate offers from several sellers
 * (developers.google.com/search/docs/appearance/structured-data/product-snippet,
 * "AggregateOffer"), and it states nothing about selling. The offers
 * themselves are on the page and link to the shops.
 *
 * Its numbers are the page's own (`shownPrice`): the range the headline shows,
 * over the offers the summary counts, never the stale or out-of-stock offers
 * the page folds away. When every offer in the range needs a minimum order,
 * the fewest is `eligibleQuantity` (allowed on AggregateOffer, a subtype of
 * Offer). When only some do, no minimum is claimed: the range then includes
 * an offer sold singly, and a minimum on the aggregate would say none is.
 *
 * No current price shown (on request only, no price, every offer out of
 * date) or a withdrawn product means no Product node at all (null): an Offer
 * without a price is invalid and inventing zero would advertise the part as
 * free, and a Product with no offers, review or rating is an invalid item in
 * Google's product snippet report. The page itself still says what it is.
 *
 * `mpn` only when a shop states the number (`statedPartNumber`, the same
 * reading the title block shows): one number a shop states that differs from
 * makhzan's, or makhzan's own when a shop states it too; none when shops
 * disagree. Never makhzan's number alone: it is read from titles and is often
 * a family prefix ("ESP32"), not a manufacturer part number. The brand the
 * page shows. Never a guessed GTIN. The description and the specs
 * (`additionalProperty`, PropertyValue, capped) both come from the one shop
 * the page's "What the shops say" opens on (never merged across shops, C4);
 * what the part fits as `isAccessoryOrSparePartFor`, only when one offer
 * alone states it.
 */
export function productJsonLd(
  product: Product,
  url: string,
  title: string,
  { description, details, now = new Date() }: ProductJsonLdOptions = {},
) {
  const shown = shownPrice(product, now);
  if (!shown) return null;
  const offers = {
    "@type": "AggregateOffer",
    priceCurrency: product.currency,
    lowPrice: shown.min,
    highPrice: shown.max,
    offerCount: shown.offerCount,
    ...(shown.availability && { availability: shown.availability }),
    ...(shown.fewest > 1 && {
      // C62 is UN/CEFACT's "one": the minimum is a count of units.
      eligibleQuantity: { "@type": "QuantitativeValue", minValue: shown.fewest, unitCode: "C62" },
    }),
    url,
  };

  const text = description?.replace(/\s+/g, " ").trim();
  const images = galleryImages(product);
  const brand = brandOf(product);
  const specs = (details?.specs ?? []).slice(0, JSON_LD_SPECS).map((row) => ({
    "@type": "PropertyValue",
    name: row.name.trim(),
    value: clampText(row.value.replace(/\s+/g, " ").trim(), JSON_LD_SPEC_VALUE),
  }));
  const fits = fitsClaim(product.offers)?.slice(0, JSON_LD_FITS) ?? [];
  const mpn = statedPartNumber(product);
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: title,
    url,
    ...(text && { description: clampText(text, JSON_LD_DESCRIPTION) }),
    ...(images.length > 0 && { image: images }),
    ...(mpn && { mpn }),
    ...(brand && { brand: { "@type": "Brand", name: brand } }),
    ...(product.category && { category: product.category.name_en }),
    ...(specs.length > 0 && { additionalProperty: specs }),
    ...(fits.length > 0 && {
      isAccessoryOrSparePartFor: fits.map((name) => ({ "@type": "Product", name })),
    }),
    offers,
  };
}

/**
 * The manufacturer part number a shop states, read as the title block reads
 * it (`partNumbers`); null when no shop states one, or shops disagree.
 */
export function statedPartNumber(product: Product): string | null {
  const { alsoStatedBy, stated, disagree } = partNumbers(product.part_number, product.offers);
  if (disagree) return null;
  if (stated) return stated.value;
  return alsoStatedBy.length > 0 ? product.part_number : null;
}

/** `text` cut at a word boundary to at most `max` characters, with an ellipsis. */
function clampText(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

/** JSON for a `<script>` tag: `<` escaped, so a title containing
 *  `</script>` cannot close the tag it is in. */
export function jsonLdText(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}

// --------------------------------------------------------------------------- //
// makhzan's own facts: what no single shop's page can say.

/** How many shops sell it, as how many listings, and how many have it in stock. */
export function shopsFact(offers: Offer[]): { shops: number; listings: number; inStockAt: number } {
  return {
    shops: shopsIn(offers),
    listings: offers.length,
    inStockAt: shopsIn(offers.filter((offer) => isInStock(offer.stock_signal))),
  };
}
