/**
 * The shop view of a product page with several offers (docs/DESIGN.md, the
 * approved mockup of November 2026): one shop's offer is "picked", and the
 * page's title, photo, highlighted row, "What the shops say" tab, primary
 * button and bottom bar follow it. On load the cheapest offer is picked (the
 * one the primary button already opens); `?shop=<slug>` picks that shop's
 * instead, so a shop view can be linked. Canonical URL, <title>, meta, JSON-LD
 * and breadcrumbs stay the product's: the shop's view is a UI feature only.
 *
 * And "Matched by AI": an offer AI matching put into the product, rather than
 * makhzan's rules, carries a badge, and the page says how many there are.
 *
 * Pure, so the rules are tested without a browser (tests/shop-view.test.ts);
 * the page and app/(site)/products/[id]/shop-view.tsx draw them.
 */
import type { Offer, Product } from "@/lib/api";
import { orderOffers, primaryOffer, type DetailSource, type GalleryPhoto } from "@/lib/product";

/** The badge's popover: a heading and a sentence, as the owner worded them. */
export const AI_TITLE = "Matched by AI";
export const AI_EXPLAINED =
  "makhzan’s AI judged this the same product as the others; the rules alone didn’t. " +
  "Check the shop’s page before buying.";
/** The badge's accessible name: what it is, and what to do about it. */
export const AI_LABEL = "Matched by AI: check the shop’s page before buying";

/** AI matching, not makhzan's rules, made it an offer of this product. */
export function isAiMatched(offer: Offer): boolean {
  return offer.matched_by === "ai";
}

/** How many of the product's offers AI matching put there: the API's count,
 *  or the offers' own marks from an API that predates it. */
export function aiMatchedCount(product: Product): number {
  return product.ai_matched_count ?? product.offers.filter(isAiMatched).length;
}

/** "2 of 5 offers were matched automatically by AI." */
export function aiNoteText(count: number, total: number): string {
  return `${count} of ${total} offers ${count === 1 ? "was" : "were"} matched automatically by AI.`;
}

/** `?shop=` as the page receives it: one slug, or null. */
export function shopParam(raw: string | string[] | undefined): string | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value ? value : null;
}

/**
 * The offer a shop leads with: of its offers, the one the primary button would
 * open (cheapest in stock, recently checked), else its first in the page's
 * order. Null for a shop with no offer here.
 */
export function shopLead(offers: Offer[], slug: string, now: Date = new Date()): Offer | null {
  const own = offers.filter((offer) => offer.supplier?.slug === slug);
  return primaryOffer(own, now) ?? orderOffers(own, now)[0] ?? null;
}

/**
 * The offer picked when the page loads: `?shop=`'s lead offer when that shop
 * sells it here, else the cheapest (the primary offer). `explicit` is whether
 * the URL chose it. Null only for a product with no offers.
 */
export function initialPick(
  offers: Offer[],
  slug: string | null,
  now: Date = new Date(),
): { offer: Offer; explicit: boolean } | null {
  const chosen = slug ? shopLead(offers, slug, now) : null;
  if (chosen) return { offer: chosen, explicit: true };
  const cheapest = primaryOffer(offers, now) ?? orderOffers(offers, now)[0] ?? null;
  return cheapest ? { offer: cheapest, explicit: false } : null;
}

/**
 * Where the gallery goes when an offer is picked: its own first photo, else
 * the first of any other offer of its shop. Null when its shop has none here,
 * and the gallery stays where it is.
 */
export function photoIndexOf(offer: Offer, offers: Offer[], photos: GalleryPhoto[]): number | null {
  const own = new Set(offer.images);
  let index = photos.findIndex((photo) => own.has(photo.src));
  if (index < 0 && offer.supplier) {
    const slug = offer.supplier.slug;
    const shops = new Set(
      offers.filter((other) => other.supplier?.slug === slug).flatMap((other) => other.images),
    );
    index = photos.findIndex((photo) => shops.has(photo.src));
  }
  return index < 0 ? null : index;
}

/**
 * Which "What the shops say" tab an offer opens: its own, else its shop's
 * first. Null for a shop that wrote nothing (it has no tab), and the tab open
 * stays open.
 */
export function detailIndexOf(offer: Offer, sources: DetailSource[]): number | null {
  const own = sources.findIndex((source) => source.offer.id === offer.id);
  if (own >= 0) return own;
  const slug = offer.supplier?.slug;
  const shops = slug ? sources.findIndex((source) => source.offer.supplier?.slug === slug) : -1;
  return shops < 0 ? null : shops;
}

/** The page's URL with `?shop=` set to a shop, every other parameter kept. */
export function shopViewUrl(current: string, slug: string): string {
  const url = new URL(current);
  url.searchParams.set("shop", slug);
  return `${url.pathname}${url.search}${url.hash}`;
}
