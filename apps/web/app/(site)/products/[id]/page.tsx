import { ChevronRight, ExternalLink } from "lucide-react";
import type { Metadata } from "next";
import { notFound, permanentRedirect } from "next/navigation";
import { preconnect } from "react-dom";

import { Breadcrumb, type Crumb } from "@/components/breadcrumb";
import { ContactButtons, ReportLink, ShopContactList } from "@/components/contact-links";
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
  type ProductSummary,
} from "@/lib/api";
import { formatCount, formatPrice, PRICE_ON_REQUEST } from "@/lib/format";
import { agoText, daysSince, freshnessTier, parseVerified } from "@/lib/freshness";
import { breadcrumbJsonLd, pageMetadata, productDescription } from "@/lib/metadata";
import {
  brandOf,
  categoryTrail,
  detailSources,
  galleryPhotos,
  jsonLdText,
  MAX_DETAIL_SOURCES,
  orderOffers,
  isStaleOffer,
  primaryOffer,
  productJsonLd,
  splitOffers,
  summarizeOffers,
  summaryText,
} from "@/lib/product";
import {
  boxSpan,
  isInStock,
  leadNotes,
  minimumLine,
  minimumWithTotal,
  needsEach,
  unitPrice,
  unitPriceText,
} from "@/lib/offers";
import { productIdFrom, routes } from "@/lib/routes";
import { absoluteUrl } from "@/lib/site";
import { departmentLabel } from "@/lib/departments";
import { cn } from "@/lib/utils";

import { Carousel } from "./carousel";
import { Details } from "./details";
import { Facts } from "./facts";
import { Gallery } from "./gallery";
import { Offers } from "./offers";
import { PartNumberLines } from "./part-numbers";
import { OptionsSection, PriceBreaksTable, TermPills } from "./terms";

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
 * Product ids are permanent (docs/decisions/0004-stable-product-ids.md). An id
 * merged into another product, or one deleted before ids were permanent,
 * redirects permanently to the product its offers went to: the old URL may be
 * shared or indexed. 308 rather than a page under the old URL, so links and
 * search engines move over.
 *
 * A product with no offers left is one every shop has withdrawn. It keeps its
 * page, as "no longer listed" (`isGone`).
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
  return product;
}

/**
 * Every shop has withdrawn it: the API says "delisted", or (between a sweep
 * and the regroup after it) it has no offer left.
 */
function isGone(product: Product): boolean {
  return product.status === "delisted" || product.offers.length === 0;
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
    // A withdrawn product's page is 200 and noindex: useful to someone who
    // followed a link (what it was, what it cost, what is like it), but not a
    // page a search should send anyone to. It drops out of the index the way a
    // 410 would, and comes back by itself if a shop lists it again.
    noindex: isGone(product),
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
  if (isGone(product)) {
    const similar = await fetchSimilar(id, 8).catch(() => []);
    return <NoLongerListed product={product} title={title} similar={similar} now={now} />;
  }
  const several = product.offers.length >= 2;
  const primary = primaryOffer(product.offers, now);
  const brand = brandOf(product);
  const soleShop = several ? null : (product.offers[0].supplier?.slug ?? null);
  // Every shop's profile, for its opening hours beside how to reach it (an
  // offer carries only the numbers and email); cached like the taxonomy.
  const shopSlugs = [
    ...new Set(product.offers.flatMap((offer) => (offer.supplier ? [offer.supplier.slug] : []))),
  ];
  // Descriptions are not part of an offer; each comes from its listing. Capped
  // like the tabs they feed, and in the offers' own order.
  const described = orderOffers(product.offers).slice(0, MAX_DETAIL_SOURCES);

  // Everything but the product itself is garnish: a failure there must not
  // take the page down with it.
  const [similar, categories, listings, shopProfiles] = await Promise.all([
    fetchSimilar(id, 8).catch(() => []),
    product.category ? fetchCategories().catch(() => []) : Promise.resolve([]),
    Promise.all(described.map((offer) => fetchListing(offer.id).catch(() => null))),
    Promise.all(shopSlugs.map((slug) => fetchSupplier(slug).catch(() => null))),
  ]);
  const shop = soleShop ? (shopProfiles[shopSlugs.indexOf(soleShop)] ?? null) : null;
  const hoursOf = new Map(
    shopProfiles.flatMap((profile) =>
      profile ? [[profile.slug, profile.contact?.opening_hours ?? []] as const] : [],
    ),
  );
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
  const photos = galleryPhotos(product);
  // The main photo is the page's largest element (its LCP) and comes from the
  // shop's server, not ours (decision 0003). Opening that connection while the
  // rest of the page streams saves the DNS, TCP and TLS round trips before the
  // photo can even be requested: 100–300 ms on a phone.
  const photoOrigin = originOf(photos[0]?.src);
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
            photos={photos}
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
                src={photos[0]?.src ?? null}
                shop={photos[0]?.shop}
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
              <PartNumberLines partNumber={product.part_number} offers={product.offers} />
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
              <Summary product={product} primary={primary} narrow={split} now={now} />
              <Offers {...splitOffers(product.offers, now)} productTitle={title} now={now} />
              <ShopsContact
                product={product}
                title={title}
                page={absoluteUrl(path)}
                hoursOf={hoursOf}
              />
            </>
          ) : (
            <OneOffer
              offer={product.offers[0]}
              now={now}
              listingCount={shop?.listing_count}
              hours={shop?.contact?.opening_hours}
              title={title}
              page={absoluteUrl(path)}
            />
          )}
        </div>

        {split && (
          <div className="min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-2">
            <Details sources={sources} />
          </div>
        )}
      </div>

      <SimilarProducts similar={similar} now={now} />

      {primary && <BottomBar offer={primary} several={several} product={product} now={now} />}
    </Container>
  );
}

/** The row of similar products that ends every product page. */
function SimilarProducts({ similar, now }: { similar: ProductSummary[]; now: Date }) {
  if (similar.length === 0) return null;
  return (
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
  );
}

/**
 * A product every shop has withdrawn. Its id is permanent, so its page stays:
 * what it was, what it last cost and when, and what is like it, so whoever
 * followed a link here can carry on. No offers, no way out to a shop (none
 * sells it), and noindex (see generateMetadata). If a shop lists it again the
 * same URL becomes the full page again.
 */
function NoLongerListed({
  product,
  title,
  similar,
  now,
}: {
  product: Product;
  title: string;
  similar: ProductSummary[];
  now: Date;
}) {
  const checked = parseVerified(product.last_verified_at);
  const gone = parseVerified(product.delisted_at ?? null);
  const query = product.part_number || titleOf(product);
  return (
    <Container className="pt-3 pb-8 lg:pt-4 lg:pb-12">
      <div className="flex gap-3 lg:gap-5">
        <PhotoFrame src={product.image} shop={product.image_shop?.name} alt={title} size={104} />
        <div className="flex min-w-0 flex-col gap-1.5">
          <h1 dir="auto" className="text-xl leading-tight lg:text-[26px]">
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

      <section
        data-no-longer-listed
        aria-labelledby="gone-heading"
        className="mt-4 flex flex-col gap-2 rounded-card border border-line bg-surface p-3.5 lg:max-w-2xl lg:p-4.5"
      >
        <h2 id="gone-heading" className="text-base font-semibold">
          No longer listed
        </h2>
        <p className="text-sm text-ink-2">
          No shop on makhzan sells this any more
          {gone ? `; the last one stopped listing it ${agoText(daysSince(gone, now))}` : ""}.
        </p>
        {(product.min_price !== null || checked) && (
          <p data-last-price className="flex flex-wrap items-baseline gap-x-1.5 text-sm text-ink-2">
            {product.min_price !== null && (
              <>
                Last price seen
                <PriceRange
                  min={product.min_price}
                  max={product.max_price}
                  currency={product.currency}
                  className="text-base text-ink"
                />
              </>
            )}
            {checked && <span>checked {agoText(daysSince(checked, now))}</span>}
          </p>
        )}
        {query && (
          <Link
            href={`/search?${new URLSearchParams({ q: query })}`}
            className="mt-1 inline-flex min-h-11 items-center self-start text-sm font-medium text-link underline"
          >
            Search for {query}
          </Link>
        )}
      </section>

      <SimilarProducts similar={similar} now={now} />
    </Container>
  );
}

const PRIMARY =
  "inline-flex h-[50px] items-center justify-center gap-2 rounded-control bg-action px-5 text-base font-semibold text-action-ink";

/**
 * One offer: its price (or "Price on request"), stock, the terms its shop
 * states (minimum order, what it fits, where it ships from, quantity prices),
 * its age, and the way out; its options under the box; then the shop.
 */
function OneOffer({
  offer,
  now,
  listingCount,
  hours,
  title,
  page,
}: {
  offer: Offer;
  now: Date;
  listingCount?: number;
  /** The shop's opening hours, as its profile has them. */
  hours?: string[];
  /** The product's title and its page's absolute URL, for "Something wrong?". */
  title: string;
  page: string;
}) {
  const verified = parseVerified(offer.last_verified_at);
  const stale = verified !== null && freshnessTier(verified, now) === "warn";
  const supplier = offer.supplier;
  const shopName = supplier?.name ?? "the shop";
  const span = boxSpan(offer);
  const reach = supplier?.contact;
  const reachable = Boolean(reach?.phone || reach?.whatsapp || reach?.email);
  const minimum = minimumLine(offer);
  return (
    <>
      <div className="mt-3 flex flex-col gap-2.5 lg:mt-5 lg:rounded-card lg:border lg:border-line lg:bg-surface lg:p-4.5">
        <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
          {span === null ? (
            <OnRequest className="text-[22px] lg:text-[26px]" />
          ) : needsEach(offer) ? (
            <span className="flex items-baseline gap-x-1.5">
              <PriceRange
                min={offer.price}
                currency={offer.currency}
                className="text-[26px] lg:text-3xl"
              />
              <Each className="text-[15px]" />
            </span>
          ) : (
            <PriceRange
              min={span.min}
              max={span.max}
              currency={offer.currency}
              className="text-[26px] lg:text-3xl"
            />
          )}
          <span data-stock className="text-sm text-ink-2">
            {span === null && isInStock(offer.stock_signal) ? (
              <span className="font-semibold text-ink">Available</span>
            ) : (
              <StockBadge
                signal={offer.stock_signal}
                quantity={offer.stock_quantity}
                className="text-sm"
              />
            )}
            {supplier && ` at ${supplier.name}`}
          </span>
        </div>
        {span === null && (
          <p data-on-request-note className="text-[13px] text-ink-2">
            {shopName} gives this price on request:{" "}
            {reachable ? "call or message them below." : "ask them on their site."}
          </p>
        )}
        {minimum && (
          <p data-minimum className="text-sm text-ink-2">
            {minimum}
          </p>
        )}
        <TermPills offer={offer} />
        <PriceBreaksTable offer={offer} shop={shopName} />
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

      <OptionsSection offer={offer} shop={shopName} now={now} />

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
      {/* Beside the card, not in it: the card is one link to the shop page. */}
      {supplier && (
        <>
          <ContactButtons
            reach={supplier.contact}
            shop={supplier.slug}
            shopName={supplier.name}
            hours={hours}
            className="mt-3"
          />
          <ReportLink
            shop={supplier.slug}
            shopName={supplier.name}
            product={title}
            page={page}
            className="mt-1"
          />
        </>
      )}
    </>
  );
}

/** "Price on request" in the price slot: in the price face, never as EGP 0. */
function OnRequest({ className }: { className?: string }) {
  return (
    <span data-price data-on-request className={cn("figure whitespace-nowrap text-ink", className)}>
      {PRICE_ON_REQUEST}
    </span>
  );
}

/** "each", beside a price of one that comes with a minimum order (C3). */
function Each({ className }: { className?: string }) {
  return (
    <span data-each className={cn("font-sans font-medium text-ink-2", className)}>
      each
    </span>
  );
}

/**
 * Several shops: each, once, with how to reach it, under the offers (rather
 * than on every row of a shop with several), and the way to report anything
 * wrong on the page.
 */
function ShopsContact({
  product,
  title,
  page,
  hoursOf,
}: {
  product: Product;
  title: string;
  page: string;
  /** Each shop's opening hours, by slug, as its profile has them. */
  hoursOf: Map<string, readonly string[]>;
}) {
  const shops = new Map<string, { slug: string; name: string; reach: Offer["supplier"] }>();
  for (const offer of product.offers) {
    if (offer.supplier && !shops.has(offer.supplier.slug)) {
      shops.set(offer.supplier.slug, {
        slug: offer.supplier.slug,
        name: offer.supplier.name,
        reach: offer.supplier,
      });
    }
  }
  const list = [...shops.values()];
  if (list.length === 0) return null;
  return (
    <div className="mt-4">
      <ShopContactList
        shops={list.map(({ slug, name, reach }) => ({
          slug,
          name,
          reach: reach?.contact,
          hours: [...(hoursOf.get(slug) ?? [])],
        }))}
      />
      <ReportLink
        shop={list[0].slug}
        shopName={list.map((s) => s.name).join(", ")}
        product={title}
        page={page}
        className="mt-1"
      />
    </div>
  );
}

/**
 * Several offers: how many are in stock where, the range of prices of one,
 * and the way out (lib/offers.ts holds the rules). Counted over the recently
 * checked offers (C2b); when every offer is stale it counts them all and
 * says, once, that the prices may be out of date.
 *
 * Under the range, whatever the lowest price needs said: its minimum order
 * with the total, the option it is, and a quantity price that beats every
 * price of one. Offers on request never enter the range or the button; with
 * nothing priced the headline is "Price on request".
 */
function Summary({
  product,
  primary,
  narrow,
  now,
}: {
  product: Product;
  primary: Offer | null;
  /** In the narrow column: the button takes the full width under the price. */
  narrow: boolean;
  now: Date;
}) {
  const summary = summarizeOffers(product.offers, now);
  const allStale = product.offers.every((offer) => isStaleOffer(offer, now));
  const newest = allStale
    ? product.offers
        .map((offer) => parseVerified(offer.last_verified_at))
        .reduce<Date | null>((a, b) => (b && (!a || b > a) ? b : a), null)
    : null;
  const { hint } = summary;
  // The lowest price, while it is in stock (or not known gone): what the
  // notes under the range and the button explain.
  const best = summary.state !== "out_of_stock" ? summary.best : null;
  const leads = best !== null && primary?.id === best.offer.id;
  const notes = leads ? leadNotes(best) : [];
  const onRequestOnly = summary.priced.length === 0 && summary.onRequest.length > 0;
  const bestShop = best?.offer.supplier?.name ?? "one shop";
  return (
    <section
      data-summary={summary.state}
      className="mt-3.5 flex flex-wrap items-center gap-x-6 gap-y-4 rounded-card border border-line bg-surface p-3.5 lg:mt-5 lg:p-4.5"
    >
      <div className="flex min-w-0 flex-col gap-1">
        <span data-summary-text className="text-[13px] text-ink-2">
          {summaryText(summary)}
        </span>
        {onRequestOnly ? (
          <OnRequest className="text-[22px] lg:text-[26px]" />
        ) : (
          <span className="flex flex-wrap items-baseline gap-x-1.5">
            <PriceRange
              min={summary.min}
              max={summary.max}
              currency={product.currency}
              className="text-[26px] lg:text-3xl"
            />
            {summary.each && summary.min !== null && <Each className="text-[15px]" />}
          </span>
        )}
        {best && needsEach(best.offer) && (
          <p data-lowest-minimum className="text-sm text-ink-2">
            Lowest needs a minimum order: {minimumWithTotal(best.offer, best.price)} at {bestShop}
          </p>
        )}
        {best?.option && (
          <p data-lowest-option className="text-[13px] text-ink-2">
            Lowest is the “{best.option}” option at {bestShop}.
          </p>
        )}
        {hint && (
          <p data-quantity-hint className="text-[13px] text-ink-2">
            Buying {hint.quantity} or more? {hint.shop} lists{" "}
            <span className="figure text-ink">{formatPrice(hint.price, hint.currency)}</span> each
            from {hint.quantity}.
          </p>
        )}
        {onRequestOnly && (
          <p className="text-[13px] text-ink-2">
            No shop publishes a price for this: ask them, below.
          </p>
        )}
        {summary.state === "out_of_stock" && (
          <p className="mt-1 text-sm text-ink-2">
            No shop has this in stock right now. Their offers are still listed below.
          </p>
        )}
        {allStale && <StaleNote lastVerified={newest} now={now} className="mt-1" />}
      </div>
      {primary?.source_url && primary.supplier && (
        <div className={cn("hidden lg:block", narrow ? "lg:w-full" : "ms-auto")}>
          <ShopLink
            href={primary.source_url}
            shop={primary.supplier.slug}
            data-primary
            className={cn(PRIMARY, narrow && "w-full")}
          >
            {leads
              ? `${unitPriceText(best)} at ${primary.supplier.name}`
              : `View at ${primary.supplier.name}`}
            <ExternalLink aria-hidden="true" className="size-4" />
          </ShopLink>
          {notes.length > 0 && (
            <p data-primary-notes className="mt-1.5 text-[13px] text-ink-2">
              {notes.join(" · ")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

/**
 * Phones only: the price, how old it is, and the way out, always on screen.
 * The body makes room for it (globals.css), so it never covers the footer.
 *
 * It says what the primary button says: the offer's price of one, with
 * "each" and the minimum when it has one, the option it is and "ships from
 * abroad" (`leadNotes`); "Price on request" for an offer with no price; for
 * one shop, the same range as its box.
 */
function BottomBar({
  offer,
  several,
  product,
  now,
}: {
  offer: Offer;
  several: boolean;
  product: Product;
  now: Date;
}) {
  if (!offer.source_url || !offer.supplier) return null;
  const summary = several ? summarizeOffers(product.offers, now) : null;
  const lead =
    summary?.best && summary.state !== "out_of_stock" && summary.best.offer.id === offer.id
      ? summary.best
      : unitPrice(offer) && { offer, price: offer.price as number, option: null };
  const span = several ? null : boxSpan(offer);
  let price: React.ReactNode;
  if (!lead) {
    price = <OnRequest className="text-[15px]" />;
  } else {
    price = (
      <span className="flex items-baseline gap-1">
        <PriceRange
          min={span?.min ?? lead.price}
          max={span?.max ?? null}
          currency={offer.currency}
          className="text-[17px]"
        />
        {needsEach(offer) && <Each className="text-[13px]" />}
      </span>
    );
  }
  const notes = lead ? leadNotes(lead) : [];
  return (
    <div
      data-bottom-bar
      className="fixed inset-x-0 bottom-0 z-20 flex items-center gap-3 border-t border-line bg-surface px-4 pt-3 pb-[calc(1.25rem+env(safe-area-inset-bottom))] lg:hidden"
    >
      <div className="flex min-w-0 flex-col">
        {price}
        {notes.length > 0 && (
          <span data-bar-notes className="text-xs text-ink-2">
            {notes.join(" · ")}
          </span>
        )}
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
