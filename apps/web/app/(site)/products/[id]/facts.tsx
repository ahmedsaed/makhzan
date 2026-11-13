import { Layers, Store, TrendingUp } from "lucide-react";

import { Freshness } from "@/components/freshness";
import { PriceRange } from "@/components/price";
import type { Offer, ProductSummary } from "@/lib/api";
import type { History } from "@/lib/history";
import { formatCount, plural } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { shopsFact, summarizeOffers } from "@/lib/product";
import { cn } from "@/lib/utils";

import { historyFactParts } from "./history";

/**
 * A link inside a line of text. On a phone its row is 44px tall and its
 * padding reaches that height without growing the line (S4); `relative` lifts
 * the padding above the neighbouring rows, so a tap there lands on it.
 */
const LINK =
  "relative whitespace-nowrap py-3.5 text-link underline underline-offset-2 hover:decoration-2 lg:py-0";

/**
 * makhzan's own facts about the product, under its title: how many shops sell
 * it and when it was checked, and the similar products at the end of the page.
 * Neither is on any shop's page, which is why they come before what the shops
 * wrote.
 *
 * Every line is a fact that holds for this product and is present: a line
 * whose data is missing is left out, never shown empty or as a placeholder.
 * The first line is always there, because a product page always has an offer.
 */
export function Facts({
  offers,
  currency,
  now,
  similar,
  history = null,
}: {
  offers: Offer[];
  currency: string;
  now: Date;
  similar: ProductSummary[];
  /** What the price history card shows; null when there is no card. */
  history?: History | null;
}) {
  const recorded = history ? historyFactParts(history, currency) : null;
  const similarPrices = similar.flatMap((item) =>
    item.min_price === null ? [] : [item.min_price],
  );
  return (
    <ul
      data-facts
      aria-label="On makhzan"
      className="mt-3 flex flex-col gap-0.5 text-[13px] leading-snug text-ink-2 lg:mt-4 lg:gap-1.5 lg:text-sm"
    >
      <Fact name="shops" icon={Store}>
        <ShopsLine offers={offers} currency={currency} now={now} />
      </Fact>
      {recorded && (
        <Fact name="history" icon={TrendingUp} linked>
          {[recorded.lowest, recorded.weeks].filter(Boolean).join(" · ")}
          {(recorded.lowest || recorded.weeks) && " · "}
          <a href="#history" className={LINK}>
            {recorded.link}
          </a>
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
  /** Holds a link: 44px tall on a phone, so the link can be (S4). */
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
 * the one the summary below shows, so the two never disagree: prices of one
 * ("each" when any has a minimum), offers on request left out, and "prices on
 * request" when nothing is priced.
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
  const summary = summarizeOffers(offers, now);
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
      {summary.min !== null ? (
        <>
          {" · "}
          <PriceRange
            min={summary.min}
            max={summary.max}
            currency={currency}
            className="text-ink-2"
          />
          {summary.each && " each"}
        </>
      ) : (
        summary.onRequest.length > 0 && " · prices on request"
      )}
    </>
  );
}
