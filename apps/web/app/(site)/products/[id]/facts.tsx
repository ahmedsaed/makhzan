import { ChartNoAxesColumn, Layers, Store } from "lucide-react";

import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { PriceRange } from "@/components/price";
import type { CategoryRef, Offer, ProductSummary } from "@/lib/api";
import { formatCount, plural } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { pricePositionText, shopsFact, summarizeOffers, type PricePosition } from "@/lib/product";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/** The product's category, with what makhzan knows about it. */
export type CategoryFact = {
  category: CategoryRef;
  /** Products in the category, from `/categories`; null when that failed. */
  count: number | null;
  /** Where this price sits among them; null when it cannot be said. */
  position: PricePosition | null;
};

/**
 * A link inside a line of text. On a phone its row is 44px tall and its
 * padding reaches that height without growing the line (S4); `relative` lifts
 * the padding above the neighbouring rows, so a tap there lands on it. Never
 * split over two lines, which would leave half a link at each end of a line.
 */
const LINK =
  "relative whitespace-nowrap py-3.5 text-link underline underline-offset-2 hover:decoration-2 lg:py-0";

/**
 * makhzan's own facts about the product, under its title: how many shops sell
 * it and when it was checked, where its price sits in its category, and the
 * similar products further down. None of it is on any shop's page, which is
 * why it comes before what the shops wrote.
 *
 * Every line is a fact that holds for this product and is present: a line
 * whose data is missing is left out, never shown empty or as a placeholder.
 * The first line is always there, because a product page always has an offer.
 */
export function Facts({
  offers,
  currency,
  now,
  category,
  similar,
}: {
  offers: Offer[];
  currency: string;
  now: Date;
  category: CategoryFact | null;
  similar: ProductSummary[];
}) {
  const categoryLine = category && categoryText(category);
  const similarPrices = similar.flatMap((item) =>
    item.min_price === null ? [] : [item.min_price],
  );
  return (
    <ul
      data-facts
      aria-label="On makhzan"
      className="mt-3 flex flex-col gap-2.5 text-[13px] leading-snug text-ink-2 lg:mt-4 lg:gap-1.5 lg:text-sm"
    >
      <Fact name="shops" icon={Store}>
        <ShopsLine offers={offers} currency={currency} now={now} />
      </Fact>
      {category && categoryLine && (
        <Fact name="category" icon={ChartNoAxesColumn} linked>
          {categoryLine}{" "}
          <Link href={routes.category(category.category.ref)} className={LINK}>
            {category.category.name_en}
          </Link>
        </Fact>
      )}
      {similar.length > 0 && (
        <Fact name="similar" icon={Layers} linked>
          <a href="#similar" className={LINK}>
            {plural(similar.length, "similar product")}
          </a>
          {similarPrices.length > 0 && (
            <>
              {", from "}
              <PriceRange
                min={Math.min(...similarPrices)}
                currency={similar[0].currency}
                className="text-ink-2"
              />
            </>
          )}
        </Fact>
      )}
    </ul>
  );
}

function Fact({
  name,
  icon: Icon,
  linked = false,
  children,
}: {
  name: string;
  icon: typeof Store;
  /** Holds a link: 44px tall on a phone, so the link can be (S4). The list's
   *  phone gap keeps a link on the second line of a wrapped row 44px from the
   *  next row's link. */
  linked?: boolean;
  children: React.ReactNode;
}) {
  return (
    <li
      data-fact={name}
      className={cn(
        "flex gap-2",
        linked ? "min-h-11 items-center lg:min-h-0 lg:items-start" : "items-start",
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn("size-4 shrink-0 text-ink-3", linked ? "lg:mt-[0.15em]" : "mt-[0.15em]")}
      />
      <span className="min-w-0">{children}</span>
    </li>
  );
}

/**
 * One shop: "Sold by 1 shop · checked 3 days ago" (the age in its F2 colour).
 * Several: "Sold by 3 shops · in stock at 2 · EGP 260 – 295", the range being
 * the one the summary below shows, so the two never disagree.
 */
function ShopsLine({ offers, currency, now }: { offers: Offer[]; currency: string; now: Date }) {
  const { shops, listings, inStockAt } = shopsFact(offers);
  const sold = `Sold by ${plural(shops, "shop")}`;
  if (listings === 1) {
    return (
      <>
        {`${sold} · `}
        <Freshness compact lastVerified={parseVerified(offers[0].last_verified_at)} now={now} />
      </>
    );
  }
  const summary = summarizeOffers(offers);
  const parts = [sold];
  if (listings > shops) parts.push(plural(listings, "listing"));
  // "Unknown" is not "no": stock nobody confirmed is said to be unconfirmed.
  parts.push(
    summary.state === "in_stock"
      ? shops === 1
        ? "in stock"
        : `in stock at ${formatCount(inStockAt)}`
      : summary.state === "unconfirmed"
        ? "stock not confirmed"
        : "none in stock",
  );
  return (
    <>
      {parts.join(" · ")}
      {summary.min !== null && (
        <>
          {" · "}
          <PriceRange
            min={summary.min}
            max={summary.max}
            currency={currency}
            className="text-ink-2"
          />
        </>
      )}
    </>
  );
}

/** "Cheaper than 70% of the 929 other products in", or failing a position,
 *  "One of 948 products in". Null when neither is known. */
function categoryText({ count, position }: CategoryFact): string | null {
  if (position) return pricePositionText(position);
  if (count !== null && count > 1) return `One of ${formatCount(count)} products in`;
  return null;
}
