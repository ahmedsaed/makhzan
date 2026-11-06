import { Link } from "@/components/link";
import { SearchField } from "@/components/search-field";
import { SiteHeader } from "@/components/site-header";
import { TradeList } from "@/components/trade-list";
import { fetchCategories, fetchStats } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { tradeSummaries } from "@/lib/trades";

/** Trades on the home page; the rest are one link away. */
const HOME_TRADES = 8;

/**
 * Two jobs: take a query from someone who knows what they want, and show the
 * shape of the catalogue to someone who doesn't. A headline, one large search,
 * the totals, then the biggest trades, each saying what is inside.
 *
 * Neither the totals nor the trades are allowed to take the page down: without
 * them it is still a working search box.
 */
export default async function HomePage() {
  const [categories, stats] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchStats().catch(() => null),
  ]);
  const trades = tradeSummaries(categories);

  return (
    <>
      <SiteHeader search={false} />
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 pb-10 md:px-6">
        <section className="flex flex-col gap-3 pt-6 pb-5 sm:pt-12 sm:pb-8">
          <h1 className="max-w-[24ch] text-[26px] leading-[1.15] font-extrabold sm:text-4xl">
            Find parts and materials across Cairo&apos;s suppliers.
          </h1>
          <SearchField autoFocus placeholder="ESP32, M8 bolt, digital caliper" className="w-full" />
          {stats && (
            <p className="text-sm text-ink-2">
              <span className="tabular">{formatCount(stats.products)}</span> products from{" "}
              <span className="tabular">{formatCount(stats.suppliers)}</span> shops. Prices
              rechecked about weekly.
            </p>
          )}
        </section>

        {trades.length > 0 && (
          <section aria-labelledby="trades-heading" className="flex flex-col gap-2">
            <h2
              id="trades-heading"
              className="font-sans text-[13px] font-semibold tracking-[0.06em] text-ink-2 uppercase"
            >
              Browse by trade
            </h2>
            <TradeList trades={trades.slice(0, HOME_TRADES)} />
            <Link
              href={routes.trades()}
              className="flex min-h-11 items-center self-start text-[15px] font-medium text-link hover:underline"
            >
              All {trades.length} trades
            </Link>
          </section>
        )}
      </main>
    </>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML — the caching
 * that matters happens in the fetch layer (see lib/api.ts), not in the page
 * shell.
 */
export const dynamic = "force-dynamic";
