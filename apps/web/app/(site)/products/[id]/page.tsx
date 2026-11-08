import { ChevronRight, ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";
import { preconnect } from "react-dom";

import { Breadcrumb, type Crumb } from "@/components/breadcrumb";
import { Freshness, StaleNote } from "@/components/freshness";
import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { PriceRange } from "@/components/price";
import { ResultCard } from "@/components/result";
import { Container } from "@/components/section";
import { ShopLink } from "@/components/shop-link";
import { StockBadge } from "@/components/stock-badge";
import {
  fetchCategories,
  fetchListing,
  fetchProduct,
  fetchProductRedirect,
  fetchSimilar,
  fetchSupplier,
  hitFromSummary,
  titleOf,
  type Offer,
  type Product,
} from "@/lib/api";
import { formatCount, formatPrice } from "@/lib/format";
import { freshnessTier, parseVerified } from "@/lib/freshness";
import { breadcrumbJsonLd, pageMetadata, productDescription } from "@/lib/metadata";
import {
  brandOf,
  categoryTrail,
  detailSources,
  galleryImages,
  jsonLdText,
  MAX_DETAIL_SOURCES,
  orderOffers,
  primaryOffer,
  productJsonLd,
  splitOffers,
  summarizeOffers,
  summaryText,
} from "@/lib/product";
import { productIdFrom, routes } from "@/lib/routes";
import { absoluteUrl } from "@/lib/site";
import { departmentLabel } from "@/lib/departments";
import { cn } from "@/lib/utils";

import { Carousel } from "./carousel";
import { Details } from "./details";
import { Facts } from "./facts";
import { Gallery } from "./gallery";
import { Offers } from "./offers";

/**
 * One product: where a buyer decides, and leaves for the shop.
 *
 * Two forms. 98.6% of products have one offer, and the page is designed for
 * that: price, stock, who sells it, their description. With two or more offers
 * the comparison appears (rule P2): a summary, then every offer in one list.
 *
 * Under the title, makhzan's own facts (Facts): how many shops sell it, when
 * it was checked, and how many similar products are at the end. The rest of
 * the text is copied from the shops; these lines are what no shop's page has,
 * so they come first.
 *
 * On a phone a fixed bar keeps the price, its age and the way out on screen.
 * On a wide screen the page goes two columns — photo and description left;
 * title, summary, primary action and offers right — and the bar goes away.
 *
 * DOM order is the phone order: photo, title and price, offers (or the shop),
 * description, similar products. The offers must never sit below shop prose.
 */

/** The page title: the product's, or its part number when it has no title. */
function displayTitle(product: Product): string {
  return titleOf(product) || product.part_number || "Untitled product";
}

/** The readable path: `/products/{id}-{words-of-the-title}`. */
function productPath(id: string, product: Product): string {
  // The product's own id, as the API spells it (lowercase), not the URL's: an
  // uppercase id in a link is the same product and redirects to one URL.
  return routes.product(product.id || id, titleOf(product) || product.part_number);
}

/**
 * An id a regroup replaced redirects, permanently, to the product its offers
 * moved to: the old URL may be shared or indexed. 308 rather than a page under
 * the old URL, so links and search engines move over.
 *
 * A product with no offers left is one every shop has withdrawn. For now that
 * is a 404, the same as an id that never existed. When products get stable ids
 * across regrouping, this is where a "no longer listed" page goes instead:
 * the title, the last price seen and when, and similar products.
 */
async function loadProduct(id: string): Promise<Product> {
  const product = await fetchProduct(id);
  if (!product) {
    const moved = await fetchProductRedirect(id).catch(() => null);
    if (moved && moved !== id) {
      // Straight to the readable URL: one hop, not two.
      const successor = await fetchProduct(moved).catch(() => null);
      permanentRedirect(successor ? productPath(moved, successor) : routes.product(moved));
    }
    notFound();
  }
  if (product.offers.length === 0) notFound();
  return product;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const id = productIdFrom((await params).id);
  const product = await loadProduct(id);
  return pageMetadata({
    // The root layout's template appends " · makhzan".
    title: displayTitle(product),
    description: productDescription(product),
    path: productPath(id, product),
    ownCard: true,
  });
}

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const param = (await params).id;
  const id = productIdFrom(param);
  const product = await loadProduct(id);
  // A bare id, an old title's slug or a mistyped one: one permanent redirect
  // to the readable URL, so links and search engines settle on it.
  const path = productPath(id, product);
  if (`/products/${param}` !== path) permanentRedirect(path);
  const now = new Date();
  const title = displayTitle(product);
  const several = product.offers.length >= 2;
  const primary = primaryOffer(product.offers);
  const brand = brandOf(product);
  const soleShop = several ? null : (product.offers[0].supplier?.slug ?? null);
  // Descriptions are not part of an offer; each comes from its listing. Capped
  // like the tabs they feed, and in the offers' own order.
  const described = orderOffers(product.offers).slice(0, MAX_DETAIL_SOURCES);

  // Everything but the product itself is garnish: a failure there must not
  // take the page down with it.
  const [similar, categories, listings, shop] = await Promise.all([
    fetchSimilar(id, 8).catch(() => []),
    product.category ? fetchCategories().catch(() => []) : Promise.resolve([]),
    Promise.all(described.map((offer) => fetchListing(offer.id).catch(() => null))),
    soleShop ? fetchSupplier(soleShop).catch(() => null) : Promise.resolve(null),
  ]);
  const descriptions = new Map(
    described.map((offer, i) => [
      offer.id,
      listings[i]?.description_en || listings[i]?.description_ar || null,
    ]),
  );
  const sources = detailSources(product.offers, descriptions);
  // With nothing written by any shop, the wide column would hold only the
  // title; the offers go there instead, as before.
  const split = sources.length > 0;
  const images = galleryImages(product);
  // The main photo is the page's largest element (its LCP) and comes from the
  // shop's server, not ours (decision 0003). Opening that connection while the
  // rest of the page streams saves the DNS, TCP and TLS round trips before the
  // photo can even be requested: 100–300 ms on a phone.
  const photoOrigin = originOf(images[0]);
  if (photoOrigin) preconnect(photoOrigin);
  const crumbs: Crumb[] | null = !product.category
    ? null
    : categories.length > 0
      ? categoryTrail(product.category, categories)
      : [
          {
            label: departmentLabel(product.category.domain),
            href: routes.department(product.category.domain),
          },
          { label: product.category.name_en, href: routes.category(product.category.ref) },
        ];

  return (
    <Container className="pt-3 pb-8 lg:pt-4 lg:pb-12">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdText(
            productJsonLd(
              product,
              absoluteUrl(path),
              title,
              // The richest shop's own words, else the same summary the meta
              // description uses: Google asks for a description either way.
              sources.find((source) => source.description)?.description ??
                productDescription(product),
            ),
          ),
        }}
      />
      {crumbs && (
        <>
          <Breadcrumb trail className="mb-3 lg:mb-4" items={crumbs} />
          <script
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: jsonLdText(breadcrumbJsonLd(crumbs, title)) }}
          />
        </>
      )}

      {/* Phones read top to bottom in DOM order: photo, title, price or
          offers, then what the shops wrote. A wide screen puts the photo and
          the way to the shop in the narrow column and gives the wide one to
          the shops' text, which is the long part:

            photo  | title
            photo  | details
            offers | details

          Row 3 is the flexible one, so the offers start right under the photo
          however long the details run. */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] lg:grid-rows-[auto_auto_1fr] lg:gap-x-10">
        {/* With several offers a phone shows a thumbnail beside the title
            instead, so the offers come up sooner. */}
        <div
          className={cn(
            several ? "hidden lg:block" : "mb-3.5 lg:mb-0",
            "lg:col-start-1 lg:row-span-2 lg:row-start-1",
          )}
        >
          <Gallery
            images={images}
            alt={title}
            // High priority whether or not a phone hides it: the phone shows
            // the same first photo as a thumbnail, so it is one download.
            priority
            frameClassName="aspect-[4/3] lg:aspect-square"
          />
        </div>

        <div className="min-w-0 lg:col-start-2 lg:row-start-1">
          <div className="flex gap-3">
            {several && (
              <PhotoFrame
                src={images[0] ?? null}
                alt={title}
                size={104}
                priority
                className="lg:hidden"
              />
            )}
            <div className="flex min-w-0 flex-col gap-1.5">
              <h1
                dir="auto"
                className={
                  several
                    ? "text-lg leading-tight lg:text-[26px]"
                    : "text-xl leading-tight lg:text-[26px]"
                }
              >
                {title}
              </h1>
              {product.part_number && (
                <p className="text-[13px] text-ink-2 lg:text-sm">
                  Part number{" "}
                  <span data-identifier className="text-ink">
                    {product.part_number}
                  </span>
                </p>
              )}
              {brand && (
                <p data-brand className="text-[13px] text-ink-2 lg:text-sm">
                  Brand · <span className="text-ink">{brand}</span>
                </p>
              )}
            </div>
          </div>
          <Facts offers={product.offers} currency={product.currency} now={now} similar={similar} />
        </div>

        <div
          data-buy
          className={cn(
            "min-w-0",
            split
              ? "lg:col-start-1 lg:row-start-3 lg:self-start"
              : "lg:col-start-2 lg:row-span-2 lg:row-start-2",
          )}
        >
          {several ? (
            <>
              <Summary product={product} primary={primary} narrow={split} />
              <Offers {...splitOffers(product.offers)} productTitle={title} now={now} />
            </>
          ) : (
            <OneOffer offer={product.offers[0]} now={now} listingCount={shop?.listing_count} />
          )}
        </div>

        {split && (
          <div className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-2">
            <Details sources={sources} />
          </div>
        )}
      </div>

      {similar.length > 0 && (
        <section
          id="similar"
          data-similar
          aria-labelledby="similar-heading"
          className="mt-8 scroll-mt-20"
        >
          <h2 id="similar-heading" className="mb-2.5 text-[15px] lg:text-lg">
            Similar products
          </h2>
          {/* A swipeable row on a phone, with arrows; a grid from `sm`. */}
          <Carousel previous="Previous products" next="Next products" buttonClassName="sm:hidden">
            <ul
              data-carousel-track
              // The scroll padding matches the side padding, so the first card
              // snaps where it starts and the strip opens at its start.
              className="-mx-4 flex snap-x scroll-px-4 gap-2.5 overflow-x-auto px-4 pb-1 *:w-36 *:shrink-0 *:snap-start sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 sm:*:w-auto md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8"
            >
              {similar.map((item) => (
                <ResultCard key={item.id} hit={hitFromSummary(item)} now={now} />
              ))}
            </ul>
          </Carousel>
        </section>
      )}

      {primary && <BottomBar offer={primary} now={now} />}
    </Container>
  );
}

const PRIMARY =
  "inline-flex h-[50px] items-center justify-center gap-2 rounded-control bg-action px-5 text-base font-semibold text-action-ink";

/** One offer: its price, stock, age and shop. */
function OneOffer({
  offer,
  now,
  listingCount,
}: {
  offer: Offer;
  now: Date;
  listingCount?: number;
}) {
  const verified = parseVerified(offer.last_verified_at);
  const stale = verified !== null && freshnessTier(verified, now) === "warn";
  const supplier = offer.supplier;
  return (
    <>
      <div className="mt-3 flex flex-col gap-2.5 lg:mt-5 lg:rounded-card lg:border lg:border-line lg:bg-surface lg:p-4.5">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          <PriceRange
            min={offer.price}
            currency={offer.currency}
            className="text-[26px] lg:text-3xl"
          />
          <span data-stock className="text-sm text-ink-2">
            <StockBadge signal={offer.stock_signal} className="text-sm" />
            {supplier && ` at ${supplier.name}`}
          </span>
        </div>
        {/* Over 45 days the note says it, with what to do; under, a quiet line. */}
        {stale ? (
          <StaleNote lastVerified={verified} now={now} />
        ) : (
          <Freshness lastVerified={verified} now={now} className="text-[13px]" />
        )}
        {offer.source_url && supplier && (
          <ShopLink
            href={offer.source_url}
            shop={supplier.slug}
            className={cn(PRIMARY, "mt-1 hidden self-start lg:inline-flex")}
          >
            View at {supplier.name}
            <ExternalLink aria-hidden="true" className="size-4" />
          </ShopLink>
        )}
      </div>

      {supplier && (
        <Link
          href={routes.shop(supplier.slug)}
          data-sold-by
          className="mt-3.5 flex items-center justify-between gap-3 rounded-card border border-line bg-surface p-3.5 hover:border-line-strong"
        >
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[13px] text-ink-2">Sold by</span>
            <span className="text-base font-semibold text-ink">{supplier.name}</span>
            <span className="text-[13px] text-ink-2">
              {listingCount !== undefined && `${formatCount(listingCount)} products · `}search this
              shop
            </span>
          </span>
          <ChevronRight aria-hidden="true" className="size-[18px] shrink-0 text-ink-2" />
        </Link>
      )}
    </>
  );
}

/** Several offers: how many are in stock where, for how much, and the way out. */
function Summary({
  product,
  primary,
  narrow,
}: {
  product: Product;
  primary: Offer | null;
  /** In the narrow column: the button takes the full width under the price. */
  narrow: boolean;
}) {
  const summary = summarizeOffers(product.offers);
  return (
    <section
      data-summary={summary.state}
      className="mt-3.5 flex flex-wrap items-center gap-x-6 gap-y-4 rounded-card border border-line bg-surface p-3.5 lg:mt-5 lg:p-4.5"
    >
      <div className="flex flex-col gap-1">
        <span className="text-[13px] text-ink-2">{summaryText(summary)}</span>
        <PriceRange
          min={summary.min}
          max={summary.max}
          currency={product.currency}
          className="text-[26px] lg:text-3xl"
        />
        {summary.state === "out_of_stock" && (
          <p className="mt-1 text-sm text-ink-2">
            No shop has this in stock right now. Their offers are still listed below.
          </p>
        )}
      </div>
      {primary?.source_url && primary.supplier && (
        <ShopLink
          href={primary.source_url}
          shop={primary.supplier.slug}
          className={cn(PRIMARY, "hidden lg:inline-flex", narrow ? "lg:w-full" : "ms-auto")}
        >
          {primary.price !== null && summary.state !== "out_of_stock"
            ? `${formatPrice(primary.price, primary.currency)} at ${primary.supplier.name}`
            : `View at ${primary.supplier.name}`}
          <ExternalLink aria-hidden="true" className="size-4" />
        </ShopLink>
      )}
    </section>
  );
}

/**
 * Phones only: the price, how old it is, and the way out, always on screen.
 * The body makes room for it (globals.css), so it never covers the footer.
 */
function BottomBar({ offer, now }: { offer: Offer; now: Date }) {
  if (!offer.source_url || !offer.supplier) return null;
  return (
    <div
      data-bottom-bar
      className="fixed inset-x-0 bottom-0 z-20 flex items-center gap-3 border-t border-line bg-surface px-4 pt-3 pb-[calc(1.25rem+env(safe-area-inset-bottom))] lg:hidden"
    >
      <div className="flex min-w-0 flex-col">
        <PriceRange min={offer.price} currency={offer.currency} className="text-[17px]" />
        <Freshness
          compact
          lastVerified={parseVerified(offer.last_verified_at)}
          now={now}
          className="self-start text-xs"
        />
      </div>
      <ShopLink
        href={offer.source_url}
        shop={offer.supplier.slug}
        className={cn(PRIMARY, "min-w-0 flex-1 px-3 text-[15px]")}
      >
        <span className="truncate">View at {offer.supplier.name}</span>
        <ExternalLink aria-hidden="true" className="size-4 shrink-0" />
      </ShopLink>
    </div>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";

/** `https://shop.example` for a photo URL, or null for anything unparseable. */
function originOf(src: string | undefined): string | null {
  if (!src) return null;
  try {
    const url = new URL(src);
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : null;
  } catch {
    return null;
  }
}
