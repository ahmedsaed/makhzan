import { ChevronRight, ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumb } from "@/components/breadcrumb";
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
  fetchSimilar,
  fetchSupplier,
  hitFromSummary,
  titleOf,
  type Offer,
  type Product,
} from "@/lib/api";
import { formatCount, formatPrice, formatPriceRange, plural } from "@/lib/format";
import { freshnessTier, parseVerified } from "@/lib/freshness";
import {
  categoryTrail,
  galleryImages,
  isInStock,
  jsonLdText,
  primaryOffer,
  productJsonLd,
  splitOffers,
  summarizeOffers,
  summaryText,
} from "@/lib/product";
import { routes } from "@/lib/routes";
import { absoluteUrl } from "@/lib/site";
import { tradeLabel } from "@/lib/trades";
import { cn } from "@/lib/utils";

import { Description } from "./description";
import { Gallery } from "./gallery";
import { Offers } from "./offers";

/**
 * One product: where a buyer decides, and leaves for the shop.
 *
 * Two forms. 98.6% of products have one offer, and the page is designed for
 * that: price, stock, who sells it, their description. With two or more offers
 * the comparison appears (rule P2): a summary, then every offer in one list.
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

/**
 * A product with no offers left is one every shop has withdrawn. For now that
 * is a 404, the same as an id that never existed. When products get stable ids
 * across regrouping, this is where a "no longer listed" page goes instead:
 * the title, the last price seen and when, and similar products.
 */
async function loadProduct(id: string): Promise<Product> {
  const product = await fetchProduct(id);
  if (!product || product.offers.length === 0) notFound();
  return product;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const product = await loadProduct(id);
  const title = displayTitle(product);
  const summary = summarizeOffers(product.offers);
  const price = formatPriceRange(summary.min, summary.max, product.currency);
  const sole = product.offers.length === 1 ? product.offers[0].supplier : null;
  const where = sole ? `at ${sole.name}` : `at ${plural(summary.shopCount, "shop")}`;
  return {
    // The root layout's template appends " · makhzan".
    title,
    description: `${title}: ${price} ${where}. Every price shows when it was last checked; buy on the shop's own page.`,
    alternates: { canonical: routes.product(id) },
  };
}

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = await loadProduct(id);
  const now = new Date();
  const title = displayTitle(product);
  const several = product.offers.length >= 2;
  const primary = primaryOffer(product.offers);
  // The description shown is the primary offer's: the shop the button opens.
  const described = primary ?? product.offers[0];
  const soleShop = several ? null : (product.offers[0].supplier?.slug ?? null);

  // Everything but the product itself is garnish: a failure there must not
  // take the page down with it.
  const [similar, categories, listing, shop] = await Promise.all([
    fetchSimilar(id, 8).catch(() => []),
    product.category ? fetchCategories().catch(() => []) : Promise.resolve([]),
    fetchListing(described.id).catch(() => null),
    soleShop ? fetchSupplier(soleShop).catch(() => null) : Promise.resolve(null),
  ]);
  const description = listing?.description_en || listing?.description_ar || null;
  const images = galleryImages(product);

  return (
    <Container className="pt-3 pb-8 lg:pt-4 lg:pb-12">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdText(productJsonLd(product, absoluteUrl(routes.product(id)), title)),
        }}
      />
      {product.category && (
        <Breadcrumb
          trail
          className="mb-3 lg:mb-4"
          items={
            categories.length > 0
              ? categoryTrail(product.category, categories)
              : [
                  {
                    label: tradeLabel(product.category.domain),
                    href: routes.trade(product.category.domain),
                  },
                  {
                    label: product.category.name_en,
                    href: routes.category(product.category.ref),
                  },
                ]
          }
        />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)] lg:grid-rows-[auto_1fr] lg:gap-x-8">
        {/* With several offers a phone shows a thumbnail beside the title
            instead, so the offers come up sooner. */}
        <div className={several ? "hidden lg:block" : "mb-3.5 lg:mb-0"}>
          <Gallery
            images={images}
            alt={title}
            priority={!several}
            frameClassName="aspect-[4/3] lg:aspect-square"
          />
        </div>

        <div className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-1">
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
            </div>
          </div>

          {several ? (
            <>
              <Summary product={product} primary={primary} />
              <Offers {...splitOffers(product.offers)} productTitle={title} now={now} />
            </>
          ) : (
            <OneOffer offer={product.offers[0]} now={now} listingCount={shop?.listing_count} />
          )}
        </div>

        {description && (
          <div className="min-w-0 lg:col-start-1 lg:row-start-2">
            <Description
              heading={
                !several
                  ? "From the shop's description"
                  : primary && isInStock(primary.stock_signal)
                    ? "From the cheapest shop's description"
                    : `From ${described.supplier?.name ?? "the shop"}'s description`
              }
              text={description}
            />
          </div>
        )}
      </div>

      {similar.length > 0 && (
        <section aria-labelledby="similar-heading" className="mt-8">
          <h2 id="similar-heading" className="mb-2.5 text-[15px] lg:text-lg">
            Similar products
          </h2>
          {/* A swipeable row on a phone, a grid from `sm`. */}
          <ul className="-mx-4 flex snap-x gap-2.5 overflow-x-auto px-4 pb-1 *:w-36 *:shrink-0 *:snap-start sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 sm:*:w-auto md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8">
            {similar.map((item) => (
              <ResultCard key={item.id} hit={hitFromSummary(item)} now={now} />
            ))}
          </ul>
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
function Summary({ product, primary }: { product: Product; primary: Offer | null }) {
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
          className={cn(PRIMARY, "ms-auto hidden lg:inline-flex")}
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
