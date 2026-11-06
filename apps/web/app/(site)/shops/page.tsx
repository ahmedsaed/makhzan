import type { Metadata } from "next";

import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { Container } from "@/components/section";
import { fetchSuppliers, type ShopSummary } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";
import { isStale, listedShops, tradesInWords } from "@/lib/shops";

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
    <Container className="max-w-4xl py-8">
      <h1 className="text-2xl sm:text-3xl">Shops</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
        makhzan lists these shops&apos; public catalogues. Each is rechecked about weekly.
      </p>

      <ul className="mt-6 overflow-hidden rounded-card border border-line bg-surface">
        {shops.map((shop) => (
          <ShopRow key={shop.slug} shop={shop} now={now} />
        ))}
      </ul>
    </Container>
  );
}

/**
 * Phones: name, then counts, trades and freshness underneath. From `md` the
 * counts and the check date become columns, so the list reads as a table.
 */
function ShopRow({ shop, now }: { shop: ShopSummary; now: Date }) {
  const stale = isStale(shop.last_verified_at, now);
  return (
    <li
      data-shop={shop.slug}
      data-stale={stale || undefined}
      className="border-b border-line last:border-b-0"
    >
      <Link
        href={routes.shop(shop.slug)}
        className="grid gap-x-5 gap-y-1 px-4 py-3 hover:bg-ground md:grid-cols-[minmax(0,1fr)_8rem_8rem_15rem] md:items-center"
      >
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="text-base font-semibold text-ink">{shop.name}</span>
          {shop.domains.length > 0 && (
            <span className="text-[13px] text-ink-2">{tradesInWords(shop.domains)}</span>
          )}
        </span>
        <span className="flex flex-wrap gap-x-1.5 text-sm text-ink-2 md:contents">
          <span className="tabular md:text-end">
            <span className="font-semibold text-ink">{formatCount(shop.listing_count)}</span>{" "}
            {shop.listing_count === 1 ? "product" : "products"}
          </span>
          <span aria-hidden="true" className="md:hidden">
            ·
          </span>
          <span className="tabular md:text-end">{formatCount(shop.in_stock_count)} in stock</span>
        </span>
        <Freshness
          lastVerified={parseVerified(shop.last_verified_at)}
          now={now}
          className="self-start text-[13px] md:justify-self-end md:self-center"
        />
      </Link>
    </li>
  );
}

/** Rendered per request: the list comes from an API this build cannot see. */
export const dynamic = "force-dynamic";
