import type { Metadata } from "next";

import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { Container } from "@/components/section";
import { fetchSuppliers, type ShopSummary } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";
import { isStale, listedShops, tradeShares, tradesInWords } from "@/lib/shops";

import { TradeBar } from "./_components/trade-bar";

export const metadata: Metadata = {
  title: "Shops",
  description:
    "Every shop makhzan lists, with how many products it has, how many are in stock, and when they were last checked.",
};

/**
 * Every shop with products, in stock and last checked. Freshness is a column
 * here, not a footnote: two shops cannot be reached from the crawler, and a
 * visitor choosing where to look deserves to know that before they look.
 */
export default async function ShopsPage() {
  const shops = listedShops(await fetchSuppliers());
  const now = new Date();

  return (
    <Container className="py-8 lg:py-10">
      <h1 className="text-2xl sm:text-3xl lg:text-4xl">Shops</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
        makhzan lists these shops&apos; public catalogues. Each is rechecked about weekly.
      </p>

      {/* One list, two shapes: rows in one card on phones, a grid of cards from
          `md`, so a wide screen is filled by shops rather than by gaps. */}
      <ul className="mt-6 overflow-hidden rounded-card border border-line bg-surface md:grid md:grid-cols-2 md:gap-3 md:overflow-visible md:rounded-none md:border-0 md:bg-transparent xl:grid-cols-4">
        {shops.map((shop) => (
          <ShopRow key={shop.slug} shop={shop} now={now} />
        ))}
      </ul>
    </Container>
  );
}

/**
 * Phones: name, trades, then counts and freshness underneath. From `md` each
 * shop is a card: name and trades, a bar of what it carries, its two counts as
 * figures, and the check date at the foot, level across a row of cards.
 */
function ShopRow({ shop, now }: { shop: ShopSummary; now: Date }) {
  const stale = isStale(shop.last_verified_at, now);
  return (
    <li
      data-shop={shop.slug}
      data-stale={stale || undefined}
      className="border-b border-line last:border-b-0 md:rounded-card md:border md:bg-surface md:last:border-b md:hover:border-line-strong"
    >
      <Link
        href={routes.shop(shop.slug)}
        className="grid gap-x-5 gap-y-1 px-4 py-3 hover:bg-ground md:flex md:h-full md:flex-col md:gap-4 md:rounded-card md:p-5 md:hover:bg-surface"
      >
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-base font-semibold text-ink md:font-display md:text-xl md:font-bold">
            {shop.name}
          </span>
          {shop.domains.length > 0 && (
            <span className="text-[13px] text-ink-2">{tradesInWords(shop.domains)}</span>
          )}
        </span>
        {shop.domains.length > 0 && (
          <TradeBar shares={tradeShares(shop.domains)} className="hidden md:flex" />
        )}
        <span className="flex flex-wrap gap-x-1.5 text-sm text-ink-2 md:grid md:grid-cols-2 md:gap-3 md:text-[13px]">
          <span className="tabular">
            <span className="font-semibold text-ink md:block md:figure md:text-2xl">
              {formatCount(shop.listing_count)}
            </span>{" "}
            {shop.listing_count === 1 ? "product" : "products"}
          </span>
          <span aria-hidden="true" className="md:hidden">
            ·
          </span>
          <span className="tabular">
            <span className="md:block md:figure md:text-2xl md:text-ink">
              {formatCount(shop.in_stock_count)}
            </span>{" "}
            in stock
          </span>
        </span>
        <Freshness
          lastVerified={parseVerified(shop.last_verified_at)}
          now={now}
          className="self-start text-[13px] md:mt-auto"
        />
      </Link>
    </li>
  );
}

/** Rendered per request: the list comes from an API this build cannot see. */
export const dynamic = "force-dynamic";
