import type { Metadata } from "next";

import { Chip, ChipBar } from "@/components/chips";
import { FacetRail } from "@/components/facet-rail";
import { FilterRail, FilterSheet } from "@/components/filter-panel";
import { Link } from "@/components/link";
import { ResultList, ViewToggle } from "@/components/result-list";
import { Container, Empty } from "@/components/section";
import { categoryNameOf, fetchCategories, searchProducts } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { routes, withParams, type SearchQuery } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

const PAGE_SIZE = 24;

const SORTS = [
  { value: "", label: "Best match" },
  { value: "price:asc", label: "Price, low first" },
  { value: "supplier_count:desc", label: "Most shops" },
  { value: "last_verified_at:desc", label: "Recently checked" },
] as const;

type RawParams = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** URL → the query this page ran. The URL is the only state; nothing is held
 *  in a component. */
function queryFrom(params: RawParams): SearchQuery {
  const offset = Number.parseInt(one(params.offset) ?? "", 10);
  const minSuppliers = Number.parseInt(one(params.min_suppliers) ?? "", 10);
  return {
    q: one(params.q) ?? "",
    category: one(params.category),
    domain: one(params.domain),
    inStock: one(params.in_stock) === "true",
    sort: one(params.sort),
    minSuppliers: Number.isFinite(minSuppliers) && minSuppliers > 1 ? minSuppliers : undefined,
    offset: Number.isFinite(offset) && offset > 0 ? offset : undefined,
  };
}

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const q = one((await searchParams).q) ?? "";
  return {
    title: q ? `${q} — Search` : "Search",
    // A filtered result set is not a page worth indexing on its own; the
    // canonical browse surfaces are the trade and category pages.
    robots: { index: false, follow: true },
  };
}

/**
 * Carried over from the previous design so the route works, on the shared
 * components; the direction-D results page is built on top of this.
 */
export default async function SearchPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const raw = await searchParams;
  const query = queryFrom(raw);
  const [result, categories] = await Promise.all([
    searchProducts({ ...query, facets: true, limit: PAGE_SIZE }),
    fetchCategories().catch(() => []),
  ]);

  const total = result.total ?? 0;
  const offset = query.offset ?? 0;
  const now = new Date();
  const filters = <FacetRail query={query} facets={result.facets} categories={categories} />;

  // Trade and category narrowings, each removable from the chip bar so the
  // result count is never unexplained.
  const active: { label: string; href: string }[] = [];
  if (query.domain) {
    active.push({
      label: tradeLabel(query.domain),
      href: routes.search({ ...query, domain: undefined, offset: undefined }),
    });
  }
  if (query.category) {
    const category = categories.find((c) => c.ref === query.category);
    active.push({
      label: category ? categoryNameOf(category) : query.category,
      href: routes.search({ ...query, category: undefined, offset: undefined }),
    });
  }

  return (
    <Container className="py-5">
      {/* Says why the ordering changed, instead of leaving it mysterious. */}
      {result.identifier_query && (
        <p className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
          <span data-identifier className="text-ink">
            {result.query}
          </span>
          Looks like a part number — ranked by identifier match first.
        </p>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <FilterRail>{filters}</FilterRail>

        <div className="min-w-0">
          <ChipBar>
            <Chip
              href={withParams("/search", raw, { in_stock: query.inStock ? null : "true" })}
              active={Boolean(query.inStock)}
            >
              In stock
            </Chip>
            <Chip
              href={withParams("/search", raw, { min_suppliers: query.minSuppliers ? null : "2" })}
              active={Boolean(query.minSuppliers)}
            >
              2+ shops
            </Chip>
            <FilterSheet activeCount={active.length}>{filters}</FilterSheet>
            {active.map((chip) => (
              <Chip key={chip.href} href={chip.href} active>
                {chip.label} ✕
              </Chip>
            ))}
          </ChipBar>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <p className="text-[13px] text-ink-2">
              <strong className="tabular text-ink">{formatCount(total)}</strong> results
            </p>
            <SortMenu raw={raw} current={query.sort ?? ""} />
            <ViewToggle />
          </div>

          {result.hits.length === 0 ? (
            <div className="mt-6">
              <Empty title="Nothing matched" hint="Try the part number on its own, or drop a filter." />
            </div>
          ) : (
            <ResultList hits={result.hits} now={now} className="-mx-4 mt-3 md:mx-0" />
          )}

          <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-3 text-sm">
            {offset > 0 ? (
              <Link
                href={routes.search({
                  ...query,
                  offset: Math.max(0, offset - PAGE_SIZE) || undefined,
                })}
                className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
              >
                Previous
              </Link>
            ) : (
              <span />
            )}
            {offset + PAGE_SIZE < total && (
              <Link
                href={routes.search({ ...query, offset: offset + PAGE_SIZE })}
                className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
              >
                Next
              </Link>
            )}
          </nav>
        </div>
      </div>
    </Container>
  );
}

/** A disclosure of links rather than a <select>: each sort is a real URL, so it
 *  works without JavaScript and stays shareable. */
function SortMenu({ raw, current }: { raw: RawParams; current: string }) {
  const selected = SORTS.find((s) => s.value === current) ?? SORTS[0];
  return (
    <details className="relative ms-auto">
      <summary className="flex h-11 cursor-pointer list-none items-center rounded-md border border-line-strong bg-surface px-3 text-[13px] sm:h-9 [&::-webkit-details-marker]:hidden">
        Sort: {selected.label}
      </summary>
      <ul className="absolute end-0 z-30 mt-1 w-56 rounded-control border border-line bg-surface p-1">
        {SORTS.map((sort) => (
          <li key={sort.value}>
            <Link
              href={withParams("/search", raw, { sort: sort.value || null })}
              className="flex min-h-11 items-center rounded-md px-2.5 text-[13px] hover:bg-ground sm:min-h-9"
            >
              {sort.label}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
