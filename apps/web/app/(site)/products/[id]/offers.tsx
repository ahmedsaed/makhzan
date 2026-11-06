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

/**
 * Every offer of a product in one list (rule P3), with the out-of-stock ones
 * folded underneath (C2) in a `<details>`, which opens without JavaScript.
 *
 * One `<table>` serves both widths: from `lg` it is the desktop comparison
 * table, and below that each row is laid out as a two-line card. One copy of
 * the markup means one set of rows, so nothing can say one thing on a phone and
 * another on a laptop.
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
        <OfferTable offers={listed} productTitle={productTitle} now={now} />
        {outOfStock.length > 0 && (
          <details data-out-of-stock className="group border-t border-line">
            <summary className="flex h-12 cursor-pointer list-none items-center gap-1.5 px-4 text-sm font-medium text-link lg:px-3.5 [&::-webkit-details-marker]:hidden">
              <span className="group-open:hidden">
                Show {plural(outOfStock.length, "out of stock offer")}
              </span>
              <span className="hidden group-open:inline">Hide out of stock offers</span>
              <ChevronDown aria-hidden="true" className="size-4 group-open:rotate-180" />
            </summary>
            <OfferTable
              offers={outOfStock}
              productTitle={productTitle}
              now={now}
              className="border-t border-line"
              hiddenHeader
            />
          </details>
        )}
      </div>
    </section>
  );
}

const CELL = "lg:px-3.5 lg:py-3 lg:align-middle";

function OfferTable({
  offers,
  productTitle,
  now,
  className,
  hiddenHeader = false,
}: {
  offers: Offer[];
  productTitle: string;
  now: Date;
  className?: string;
  /** The folded table repeats the columns of the one above it. */
  hiddenHeader?: boolean;
}) {
  return (
    <table className={`w-full border-collapse text-sm max-lg:block ${className ?? ""}`}>
      <thead className={hiddenHeader ? "sr-only" : "max-lg:hidden"}>
        <tr className="border-b border-line text-start text-xs tracking-wide text-ink-2 uppercase">
          <th scope="col" className={`${CELL} text-start font-semibold`}>
            Their listing
          </th>
          <th scope="col" className={`${CELL} text-start font-semibold`}>
            Shop
          </th>
          <th scope="col" className={`${CELL} text-start font-semibold`}>
            Checked
          </th>
          <th scope="col" className={`${CELL} text-end font-semibold`}>
            Price
          </th>
          <th scope="col" className={CELL}>
            <span className="sr-only">Link</span>
          </th>
        </tr>
      </thead>
      <tbody className="max-lg:block">
        {offers.map((offer) => (
          <OfferRow key={offer.id} offer={offer} productTitle={productTitle} now={now} />
        ))}
      </tbody>
    </table>
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
    <tr
      data-offer={offer.id}
      className="border-b border-line last:border-b-0 max-lg:grid max-lg:grid-cols-[auto_minmax(0,1fr)_auto] max-lg:items-start max-lg:gap-x-1.5 max-lg:gap-y-1 max-lg:px-4 max-lg:py-3 max-lg:[grid-template-areas:'title_title_price'_'shop_fresh_view']"
    >
      <td className={`${CELL} [grid-area:title]`}>
        <span
          data-offer-title
          dir="auto"
          className="line-clamp-2 text-[15px] leading-snug font-medium text-ink lg:text-sm"
        >
          {title}
        </span>
      </td>
      <td className={`${CELL} text-[13px] [grid-area:shop] lg:text-sm`}>
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
      </td>
      <td className={`${CELL} text-[13px] [grid-area:fresh] lg:text-sm lg:whitespace-nowrap`}>
        <span aria-hidden="true" className="me-1.5 text-ink-3 lg:hidden">
          ·
        </span>
        <Freshness lastVerified={parseVerified(offer.last_verified_at)} now={now} />
      </td>
      <td className={`${CELL} text-end [grid-area:price] max-lg:ps-3`}>
        <PriceRange min={offer.price} currency={offer.currency} className="text-base" />
      </td>
      <td className={`${CELL} text-end [grid-area:view] max-lg:ps-3`}>
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
      </td>
    </tr>
  );
}
