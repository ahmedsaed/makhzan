/**
 * The decisions behind the product page, as plain functions: which offers are
 * listed and in what order, what the summary says, which shop the primary
 * button opens, and what search engines are told. Kept out of the JSX so each
 * one is tested on its own.
 */
import type { Crumb } from "@/components/breadcrumb";
import type { Category, CategoryRef, Offer, Product, StockSignal } from "@/lib/api";
import {
  checkedAt,
  compareOffers,
  comparisonText,
  isInStock,
  isOutOfStock,
  isStaleOffer,
  orderOffers,
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

const AVAILABILITY: Partial<Record<StockSignal, string>> = {
  in_stock: "https://schema.org/InStock",
  low_stock: "https://schema.org/LimitedAvailability",
  out_of_stock: "https://schema.org/OutOfStock",
  made_to_order: "https://schema.org/MadeToOrder",
};

/** Longest description we put in structured data; the page has the rest. */
const JSON_LD_DESCRIPTION = 500;

/**
 * schema.org Product for search engines, marked up as what the page is: a
 * comparison of other shops' offers, not a shop selling the product.
 *
 * Always an AggregateOffer (low and high price, how many offers, whether any
 * is in stock), never an Offer, even for one shop. Google reads a page with an
 * Offer as a merchant selling the product there (a "merchant listing") and
 * then asks for what only a seller has: shipping, a return policy, a GTIN.
 * An AggregateOffer is what Google documents for product snippets on pages
 * that compare offers, and it states nothing about selling. The offers
 * themselves are on the page and link to the shops.
 *
 * Identifiers only when we have them: the part number as `mpn`, the brand
 * when a shop states it. Never a guessed GTIN. Offers without a price are
 * left out: inventing zero would advertise the part as free.
 */
export function productJsonLd(
  product: Product,
  url: string,
  title: string,
  description?: string | null,
) {
  const priced = orderOffers(product.offers).filter((offer) => offer.price !== null);
  let offers: object | undefined;
  if (priced.length > 0) {
    const prices = priced.map((item) => item.price as number);
    const availability = priced.some((item) => isInStock(item.stock_signal))
      ? "https://schema.org/InStock"
      : AVAILABILITY[priced[0].stock_signal];
    offers = {
      "@type": "AggregateOffer",
      priceCurrency: product.currency,
      lowPrice: Math.min(...prices),
      highPrice: Math.max(...prices),
      offerCount: priced.length,
      ...(availability && { availability }),
      url,
    };
  }

  const text = description?.replace(/\s+/g, " ").trim();
  const images = galleryImages(product);
  const brand = brandOf(product);
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: title,
    url,
    ...(text && { description: clampText(text, JSON_LD_DESCRIPTION) }),
    ...(images.length > 0 && { image: images }),
    ...(product.part_number && { mpn: product.part_number }),
    ...(brand && { brand: { "@type": "Brand", name: brand } }),
    ...(product.category && { category: product.category.name_en }),
    ...(offers && { offers }),
  };
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
