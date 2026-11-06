import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumb } from "@/components/breadcrumb";
import { Link } from "@/components/link";
import { ResultList, ViewToggle } from "@/components/result-list";
import { Container, Empty } from "@/components/section";
import { categoryNameOf, fetchCategories, searchProducts } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { joinRef, routes } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

const PAGE_SIZE = 24;

/**
 * One category, addressed through its trade because category slugs are unique
 * per trade only. The same query search runs, with `category` pinned.
 *
 * Carried over from the previous design so the route works; the direction-D
 * category page (the trade page, narrowed) is built on top of this.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ trade: string; category: string }>;
}): Promise<Metadata> {
  const { trade, category: slug } = await params;
  const categories = await fetchCategories(trade).catch(() => []);
  const category = categories.find((c) => c.slug === slug);
  return {
    title: category ? categoryNameOf(category) : slug,
    alternates: { canonical: routes.category(joinRef(trade, slug)) },
  };
}

export default async function CategoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ trade: string; category: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { trade, category: slug } = await params;
  const raw = await searchParams;
  const offsetRaw = Number.parseInt(
    (Array.isArray(raw.offset) ? raw.offset[0] : raw.offset) ?? "",
    10,
  );
  const offset = Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : 0;

  const ref = joinRef(trade, slug);
  const categories = await fetchCategories(trade);
  const category = categories.find((c) => c.ref === ref);
  if (!category) notFound();

  const result = await searchProducts({ category: ref, domain: trade, limit: PAGE_SIZE, offset });
  const total = result.total ?? 0;
  const here = routes.category(ref);

  return (
    <Container className="py-6">
      <Breadcrumb
        className="mb-3"
        items={[
          { label: "Trades", href: routes.trades() },
          { label: tradeLabel(trade), href: routes.trade(trade) },
          { label: categoryNameOf(category) },
        ]}
      />
      <h1 className="text-2xl">{categoryNameOf(category)}</h1>
      <div className="mt-2 mb-3 flex items-center gap-2">
        <p className="text-[13px] text-ink-2">
          <strong className="tabular text-ink">{formatCount(total)}</strong> results
        </p>
        <ViewToggle className="ms-auto" />
      </div>

      {result.hits.length === 0 ? (
        <Empty title="Nothing matched" hint="This category is empty right now." />
      ) : (
        <ResultList hits={result.hits} now={new Date()} className="-mx-4 md:mx-0" />
      )}

      <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-3 text-sm">
        {offset > 0 ? (
          <Link
            href={offset - PAGE_SIZE > 0 ? `${here}?offset=${offset - PAGE_SIZE}` : here}
            className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
          >
            Previous
          </Link>
        ) : (
          <span />
        )}
        {offset + PAGE_SIZE < total && (
          <Link
            href={`${here}?offset=${offset + PAGE_SIZE}`}
            className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
          >
            Next
          </Link>
        )}
      </nav>
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
