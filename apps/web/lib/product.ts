/**
 * The decisions behind the product page, as plain functions: which offers are
 * listed and in what order, what the summary says, which shop the primary
 * button opens, and what search engines are told. Kept out of the JSX so each
 * one is tested on its own.
 */
import type { Crumb } from "@/components/breadcrumb";
import type { Category, CategoryRef, Offer, Product, StockSignal } from "@/lib/api";
import { plural } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

/** Low stock is still stock: the shop says it can sell one today. */
export function isInStock(signal: StockSignal): boolean {
  return signal === "in_stock" || signal === "low_stock";
}

export function isOutOfStock(offer: Offer): boolean {
  return offer.stock_signal === "out_of_stock";
}

function checkedAt(offer: Offer): number {
  return parseVerified(offer.last_verified_at)?.getTime() ?? 0;
}

/**
 * Lowest price first. An offer without a price goes after every priced one —
 * "Price on request" must never sort as free — and equal prices put the more
 * recently checked offer first, since it is the likelier to still be true.
 */
export function orderOffers(offers: Offer[]): Offer[] {
  return [...offers].sort((a, b) => {
    if (a.price === null || b.price === null) {
      if (a.price !== b.price) return a.price === null ? 1 : -1;
    } else if (a.price !== b.price) {
      return a.price - b.price;
    }
    return checkedAt(b) - checkedAt(a);
  });
}

/**
 * The offers list, and the out-of-stock offers folded beneath it (rule C2).
 *
 * When every offer is out of stock nothing is folded: a fold holding the whole
 * list would leave a page that says nothing, and the reader came to see them.
 */
export function splitOffers(offers: Offer[]): {
  listed: Offer[];
  outOfStock: Offer[];
} {
  const ordered = orderOffers(offers);
  const outOfStock = ordered.filter(isOutOfStock);
  if (outOfStock.length === ordered.length) return { listed: ordered, outOfStock: [] };
  return { listed: ordered.filter((offer) => !isOutOfStock(offer)), outOfStock };
}

/**
 * What the summary above the offers counts. `in_stock` when any shop says it
 * has stock; `unconfirmed` when none says so but some do not say it is gone
 * (an "unknown" signal is not a "no"); `out_of_stock` when every shop says it is.
 */
export type OfferSummary = {
  state: "in_stock" | "unconfirmed" | "out_of_stock";
  offerCount: number;
  shopCount: number;
  min: number | null;
  max: number | null;
};

function shopsIn(offers: Offer[]): number {
  return new Set(offers.map((offer) => offer.supplier?.slug ?? offer.id)).size;
}

export function summarizeOffers(offers: Offer[]): OfferSummary {
  const inStock = offers.filter((offer) => isInStock(offer.stock_signal));
  const notGone = offers.filter((offer) => !isOutOfStock(offer));
  const [state, counted]: [OfferSummary["state"], Offer[]] =
    inStock.length > 0
      ? ["in_stock", inStock]
      : notGone.length > 0
        ? ["unconfirmed", notGone]
        : ["out_of_stock", offers];
  const prices = counted.flatMap((offer) => (offer.price === null ? [] : [offer.price]));
  return {
    state,
    offerCount: counted.length,
    shopCount: shopsIn(counted),
    min: prices.length ? Math.min(...prices) : null,
    max: prices.length ? Math.max(...prices) : null,
  };
}

/** "5 offers in stock at 3 shops". */
export function summaryText(summary: OfferSummary): string {
  const { offerCount, shopCount } = summary;
  if (summary.state === "in_stock") {
    return `${plural(offerCount, "offer")} in stock at ${plural(shopCount, "shop")}`;
  }
  if (summary.state === "unconfirmed") {
    return `${plural(offerCount, "offer")} at ${plural(shopCount, "shop")}, stock not confirmed`;
  }
  return shopCount === 1 ? "Out of stock" : `Out of stock at all ${shopCount} shops`;
}

/**
 * The offer the primary button opens: the cheapest in stock; failing that the
 * cheapest not known to be gone; and when every shop is out of stock, the most
 * recently checked, since it is the one most likely to have restocked. Only an
 * offer with somewhere to go qualifies.
 */
export function primaryOffer(offers: Offer[]): Offer | null {
  const linkable = orderOffers(offers).filter((offer) => offer.source_url && offer.supplier);
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

/** The product's own photo first, then every offer's, each once. */
export function galleryImages(product: Product): string[] {
  const all = [product.image, ...product.offers.flatMap((offer) => offer.images)];
  const unique = [...new Set(all.filter((src): src is string => Boolean(src)))];
  return unique.slice(0, MAX_PHOTOS);
}

/**
 * Trade › group › category, walked up the category's parents. Every crumb is a
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
    { label: tradeLabel(category.domain), href: routes.trade(category.domain) },
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

/**
 * schema.org Product for search engines: one Offer, or an AggregateOffer over
 * several. Every offer's `url` is this page, not the shop's: the page is what
 * we vouch for, and it carries the freshness warning a shop's page does not.
 *
 * Offers without a price are left out — an Offer must state one, and inventing
 * zero would advertise the part as free.
 */
export function productJsonLd(product: Product, url: string, title: string) {
  const priced = orderOffers(product.offers).filter((offer) => offer.price !== null);
  const offer = (item: Offer) => ({
    "@type": "Offer",
    price: item.price,
    priceCurrency: item.currency,
    ...(AVAILABILITY[item.stock_signal] && {
      availability: AVAILABILITY[item.stock_signal],
    }),
    url,
    ...(item.supplier && {
      seller: { "@type": "Organization", name: item.supplier.name },
    }),
  });

  let offers: object | undefined;
  if (priced.length === 1) {
    offers = offer(priced[0]);
  } else if (priced.length > 1) {
    const prices = priced.map((item) => item.price as number);
    offers = {
      "@type": "AggregateOffer",
      priceCurrency: product.currency,
      lowPrice: Math.min(...prices),
      highPrice: Math.max(...prices),
      offerCount: priced.length,
      offers: priced.map(offer),
    };
  }

  const images = galleryImages(product);
  return {
    "@context": "https://schema.org",
    "@type": "Product",
    name: title,
    url,
    ...(images.length > 0 && { image: images }),
    ...(product.part_number && { mpn: product.part_number }),
    ...(product.brand && { brand: { "@type": "Brand", name: product.brand } }),
    ...(product.category && { category: product.category.name_en }),
    ...(offers && { offers }),
  };
}

/** JSON for a `<script>` tag: `<` escaped, so a title containing
 *  `</script>` cannot close the tag it is in. */
export function jsonLdText(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
