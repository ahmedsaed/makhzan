import { Link } from "@/components/link";
import { ResultRow } from "@/components/result";
import { SearchField } from "@/components/search-field";
import { Container, SectionHeading } from "@/components/section";
import { SiteHeader } from "@/components/site-header";
import { fetchCategories, fetchStats, searchProducts } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { tradesFrom } from "@/lib/trades";

/**
 * Two jobs: take a query from someone who knows what they want, and show the
 * shape of the catalogue to someone who doesn't.
 *
 * Carried over from the previous design so the route works; the direction-D
 * home (trades as rows with their top categories) is built on top of this.
 */
export default async function HomePage() {
  const [categories, stats, multi] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchStats().catch(() => null),
    searchProducts({ minSuppliers: 2, sort: "supplier_count:desc", limit: 6 }).catch(() => null),
  ]);
  const trades = tradesFrom(categories);
  const now = new Date();

  return (
    <>
      <SiteHeader search={false} />
      <main className="flex-1">
        <section className="border-b border-line bg-surface">
          <Container className="flex flex-col items-center gap-5 py-12 text-center sm:py-16">
            <h1 className="max-w-[22ch] text-3xl leading-tight font-extrabold sm:text-4xl">
              Find parts across Egypt&apos;s shops
            </h1>
            <SearchField
              autoFocus
              placeholder="LM358, ESP32, 0805 resistor…"
              className="w-full max-w-xl"
            />
            {stats && (
              <p className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm text-ink-2">
                <span>
                  <strong className="figure text-ink">{formatCount(stats.products)}</strong>{" "}
                  products
                </span>
                <span>
                  <strong className="figure text-ink">{formatCount(stats.suppliers)}</strong> shops
                </span>
                <span>rechecked about weekly</span>
              </p>
            )}
          </Container>
        </section>

        <Container className="py-8">
          <SectionHeading>Trades</SectionHeading>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {trades.map((trade) => (
              <li key={trade.domain}>
                <Link
                  href={routes.trade(trade.domain)}
                  className="flex h-full flex-col gap-0.5 rounded-card border border-line bg-surface px-3 py-2.5 hover:border-line-strong"
                >
                  <span className="text-sm leading-tight font-semibold text-ink">
                    {trade.label}
                  </span>
                  <span className="tabular text-xs text-ink-3">{formatCount(trade.count)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Container>

        {multi && multi.hits.length > 0 && (
          <Container className="pb-12">
            <SectionHeading>Sold by more than one shop</SectionHeading>
            <ul className="border-t border-line bg-surface">
              {multi.hits.map((hit) => (
                <ResultRow key={hit.id} hit={hit} now={now} />
              ))}
            </ul>
          </Container>
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
