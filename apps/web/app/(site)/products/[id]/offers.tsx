import { ChevronDown, ExternalLink } from "lucide-react";

import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { PriceRange } from "@/components/price";
import { ShopLink } from "@/components/shop-link";
import { StockBadge } from "@/components/stock-badge";
import { titleOf, type Offer } from "@/lib/api";
import { plural } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { isInStock } from "@/lib/product";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * Every offer of a product in one list (rule P3), with the out-of-stock ones
 * folded underneath (C2) in a `<details>`, which opens without JavaScript.
 *
 * Each offer is a two-line card at every width: on a wide screen the offers
 * sit in the page's narrow column, under the photo, and the wide one is left
 * to what the shops wrote. One layout also means nothing can say one thing on
 * a phone and another on a laptop.
 */
export function Offers({
  listed,
  outOfStock,
  productTitle,
  now,
}: {
  listed: Offer[];
  outOfStock: Offer[];
  productTitle: string;
  now: Date;
}) {
  return (
    <section aria-labelledby="offers-heading" className="mt-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="offers-heading" className="text-[17px] lg:text-lg">
          Offers
        </h2>
        <span className="text-[13px] text-ink-2">lowest price first</span>
      </div>
      {/* Not more than this: what differs between two shops' titles is for the
          reader to see, and a sentence claiming it would be a guess. */}
      <p className="mt-1 mb-2.5 text-[13px] leading-snug text-ink-2">
        Each offer shows the shop&apos;s own title.
      </p>
      <div className="-mx-4 overflow-hidden border-y border-line bg-surface md:mx-0 md:rounded-card md:border">
        <OfferList offers={listed} productTitle={productTitle} now={now} />
        {outOfStock.length > 0 && (
          <details data-out-of-stock className="group border-t border-line">
            <summary className="flex h-12 cursor-pointer list-none items-center gap-1.5 px-4 text-sm font-medium text-link [&::-webkit-details-marker]:hidden">
              <span className="group-open:hidden">
                Show {plural(outOfStock.length, "out of stock offer")}
              </span>
              <span className="hidden group-open:inline">Hide out of stock offers</span>
              <ChevronDown aria-hidden="true" className="size-4 group-open:rotate-180" />
            </summary>
            <OfferList
              offers={outOfStock}
              productTitle={productTitle}
              now={now}
              className="border-t border-line"
            />
          </details>
        )}
      </div>
    </section>
  );
}

function OfferList({
  offers,
  productTitle,
  now,
  className,
}: {
  offers: Offer[];
  productTitle: string;
  now: Date;
  className?: string;
}) {
  return (
    <ul className={cn("text-sm", className)}>
      {offers.map((offer) => (
        <OfferRow key={offer.id} offer={offer} productTitle={productTitle} now={now} />
      ))}
    </ul>
  );
}

/**
 * One offer, led by the shop's own title: a shop legitimately lists several
 * variants of one product, and without the title those rows are identical
 * lines with different prices (rule P3).
 *
 * Self-contained on purpose — nothing here reads a neighbouring row — so that
 * variant groups can later wrap runs of rows without rewriting them.
 */
function OfferRow({ offer, productTitle, now }: { offer: Offer; productTitle: string; now: Date }) {
  const supplier = offer.supplier;
  const title = titleOf(offer) || productTitle;
  return (
    <li
      data-offer={offer.id}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-1.5 gap-y-1 border-b border-line px-4 py-3 [grid-template-areas:'title_title_price'_'shop_fresh_view'] last:border-b-0"
    >
      <div className="[grid-area:title]">
        <span
          data-offer-title
          dir="auto"
          className="line-clamp-2 text-[15px] leading-snug font-medium text-ink lg:text-sm"
        >
          {title}
        </span>
      </div>
      <div className="text-[13px] [grid-area:shop]">
        <span className="flex flex-wrap items-baseline gap-x-1.5">
          {supplier ? (
            <Link
              href={routes.shop(supplier.slug)}
              className="font-semibold whitespace-nowrap text-ink hover:underline"
            >
              {supplier.name}
            </Link>
          ) : (
            <span className="text-ink-2">Unknown shop</span>
          )}
          {/* In stock is the norm in this list and goes unsaid; anything else
              is the row's business. */}
          {!isInStock(offer.stock_signal) && <StockBadge signal={offer.stock_signal} />}
        </span>
      </div>
      <div className="text-[13px] [grid-area:fresh]">
        <span aria-hidden="true" className="me-1.5 text-ink-3">
          ·
        </span>
        <Freshness lastVerified={parseVerified(offer.last_verified_at)} now={now} />
      </div>
      <div className="ps-3 text-end [grid-area:price]">
        <PriceRange min={offer.price} currency={offer.currency} className="text-base" />
      </div>
      <div className="ps-3 text-end [grid-area:view]">
        {offer.source_url && supplier && (
          <ShopLink
            href={offer.source_url}
            shop={supplier.slug}
            aria-label={`View at ${supplier.name}`}
            className="inline-flex h-11 items-center gap-1 rounded-control border-[1.5px] border-link px-3 text-sm font-semibold whitespace-nowrap text-link lg:h-9"
          >
            View
            <ExternalLink aria-hidden="true" className="size-3.5" />
          </ShopLink>
        )}
      </div>
    </li>
  );
}
