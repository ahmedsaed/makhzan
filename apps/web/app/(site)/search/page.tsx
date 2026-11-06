import type { Metadata } from "next";

import { Chip, ChipBar } from "@/components/chips";
import { FilterRail, FilterSheet } from "@/components/filter-panel";
import { Link } from "@/components/link";
import { ResultList, ViewToggle } from "@/components/result-list";
import { ResultsFilters } from "@/components/results-filters";
import { Container } from "@/components/section";
import { SortSelect } from "@/components/sort-select";
import {
  categoryNameOf,
  fetchCategories,
  fetchSupplier,
  searchProducts,
  type Category,
  type SearchResponse,
} from "@/lib/api";
import { formatCount, formatPriceRange, plural } from "@/lib/format";
import { routes } from "@/lib/routes";
import {
  PAGE_SIZE,
  SORTS,
  activeFilterCount,
  apiParams,
  flatParams,
  groupCategoryFacet,
  hiddenOutOfStock,
  parseResultsQuery,
  resultsLinks,
  topCategories,
  type RawParams,
  type ResultsQuery,
} from "@/lib/results-query";
import { tradeLabel, tradesFrom } from "@/lib/trades";

const PATHNAME = "/search";

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { q } = parseResultsQuery(await searchParams);
  return {
    // The root layout appends " · makhzan".
    title: q || "Search",
    // A filtered result set is not a page worth indexing on its own; the
    // canonical browse surfaces are the trade and category pages.
    robots: { index: false, follow: true },
  };
}

/**
 * Results: the chip bar, top categories for the query, a toolbar (count, the
 * hidden out-of-stock count, sort, list/grid), the results and paging. On
 * desktop the category and price filters move from a bottom sheet to a rail.
 *
 * The URL is the only state (lib/results-query.ts has the contract), and
 * every control is a link or a GET form, so all of it works without
 * JavaScript.
 */
export default async function SearchPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  const raw = await searchParams;
  const query = parseResultsQuery(raw);

  if (!query.q && !query.category && !query.domain && !query.shop) {
    return <Landing />;
  }

  const params = apiParams(query);
  // Counts only: one hit is the least the API will return.
  const countOnly = { limit: 1, offset: undefined, sort: undefined };
  const [result, unfiltered, uncategorized, categories, shop] = await Promise.all([
    searchProducts(params).catch(() => null),
    // Facets are counted over the filtered set, so how many the in-stock
    // default hides needs the same search without it.
    query.inStockOnly
      ? searchProducts({ ...params, ...countOnly, inStock: false }).catch(() => null)
      : null,
    // Likewise the category list: with one picked, the main search's facet
    // holds only that one, and the others must stay pickable.
    query.category
      ? searchProducts({
          ...params,
          ...countOnly,
          category: undefined,
        }).catch(() => null)
      : null,
    fetchCategories().catch((): Category[] => []),
    query.shop ? fetchSupplier(query.shop).catch(() => null) : null,
  ]);

  const shopName = query.shop ? (shop?.name ?? query.shop) : undefined;
  const heading = <Heading query={query} raw={raw} shopName={shopName} />;

  if (!result) {
    return (
      <Container className="py-5">
        {heading}
        <div role="alert" className="mt-4 rounded-card border border-line bg-surface px-5 py-8">
          <p className="font-display text-base font-bold text-ink">Search is not answering</p>
          <p className="mt-1 text-sm text-ink-2">
            The catalogue could not be reached just now. Try again in a minute.
          </p>
        </div>
      </Container>
    );
  }

  const links = resultsLinks(PATHNAME, raw, query);
  const total = result.total ?? 0;
  const hidden = query.inStockOnly ? hiddenOutOfStock(unfiltered?.facets) : 0;
  const names = new Map(categories.map((c) => [c.ref, categoryNameOf(c)]));
  const now = new Date();

  // The category list, counted as if each were picked.
  const wide: SearchResponse = uncategorized ?? result;
  const groups = groupCategoryFacet(wide.facets?.category_ref);
  if (query.category && !groups.some((g) => g.categories.some((c) => c.ref === query.category))) {
    // The picked category must stay visible (and checked) even at zero.
    const domain = query.category.split(":")[0];
    groups.push({
      domain,
      count: 0,
      categories: [{ ref: query.category, count: 0 }],
    });
  }
  const filters = (variant: "sheet" | "rail") => (
    <ResultsFilters
      pathname={PATHNAME}
      raw={raw}
      query={query}
      groups={groups}
      names={names}
      anyCount={wide.total ?? total}
      variant={variant}
    />
  );

  // Narrowings beyond the two everyday chips, each removable from the bar so
  // the result count is never unexplained.
  const active: { label: string; href: string }[] = [];
  if (query.domain) {
    active.push({
      label: tradeLabel(query.domain),
      href: links.clear("domain"),
    });
  }
  if (query.category) {
    active.push({
      label: names.get(query.category) ?? query.category,
      href: links.clear("category"),
    });
  }
  if (query.minPrice !== undefined || query.maxPrice !== undefined) {
    active.push({
      label: priceLabel(query),
      href: links.clear("min_price", "max_price"),
    });
  }
  const sheetCount = [query.category, query.minPrice ?? query.maxPrice].filter(
    (v) => v !== undefined,
  ).length;

  const top = query.q && !query.category ? topCategories(result.facets?.category_ref) : [];

  return (
    <Container className="py-4 lg:py-5">
      {heading}

      {/* Says why the ordering changed, instead of leaving it mysterious. */}
      {result.identifier_query && (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border border-line bg-surface px-3 py-2 text-[13px] text-ink-2">
          <span data-identifier className="font-mono font-medium text-ink">
            {result.query}
          </span>
          Looks like a part number — ranked by identifier match first.
        </p>
      )}

      {/* One grid, two orders: on a phone chips → top categories → results;
          from `lg` the top categories span the page and the rail runs down the
          left beside the chips and results. */}
      <div className="mt-3 flex flex-col gap-3 lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:grid-rows-[auto_auto_1fr] lg:gap-x-8 lg:gap-y-4">
        <ChipBar className="lg:col-start-2 lg:row-start-2">
          <Chip href={links.inStock} active={query.inStockOnly}>
            In stock
          </Chip>
          <Chip href={links.twoShops} active={Boolean(query.minSuppliers)}>
            2+ shops
          </Chip>
          <FilterSheet activeCount={sheetCount}>{filters("sheet")}</FilterSheet>
          {active.map((chip) => (
            <Chip key={chip.href} href={chip.href} active>
              {chip.label} ✕
            </Chip>
          ))}
        </ChipBar>

        {top.length > 0 && (
          <section
            aria-labelledby="top-categories"
            className="flex flex-col gap-2 lg:col-span-2 lg:row-start-1"
          >
            <h2 id="top-categories" className="font-sans text-[13px] font-semibold text-ink-2">
              Top categories for “{query.q}”
            </h2>
            <ul className="-mx-4 flex [scrollbar-width:none] gap-2 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:px-0">
              {top.map(({ ref, count }) => (
                <li key={ref} className="shrink-0">
                  <Link
                    href={links.category(ref)}
                    className="flex flex-col gap-0.5 rounded-control border border-line bg-surface px-3 py-2 text-ink hover:border-line-strong"
                  >
                    <span className="text-xs text-ink-3">{tradeLabel(ref.split(":")[0])} ›</span>
                    <span className="text-sm font-semibold">
                      {names.get(ref) ?? ref}{" "}
                      <span className="font-normal text-ink-3 tabular">{formatCount(count)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <FilterRail className="lg:col-start-1 lg:row-span-2 lg:row-start-2">
          {filters("rail")}
        </FilterRail>

        <div className="min-w-0 lg:col-start-2 lg:row-start-3">
          {/* A phone has no room for all three on one line: the count gets its
              own, sort and the view toggle share the next. */}
          <div className="flex flex-wrap items-center gap-2">
            <p
              data-count
              className="basis-full text-[13px] text-ink-2 sm:me-auto sm:basis-auto lg:text-sm"
            >
              <span className="tabular">{plural(total, "result")}</span>
              {hidden > 0 && (
                <>
                  {" · "}
                  <Link
                    href={links.showOutOfStock}
                    className="text-link underline-offset-2 hover:underline"
                  >
                    {formatCount(hidden)} more out of stock
                  </Link>
                </>
              )}
            </p>
            {total > 0 && (
              <>
                <SortSelect
                  pathname={PATHNAME}
                  params={flatParams(raw)}
                  options={SORTS}
                  current={query.sort ?? ""}
                  className="me-auto sm:me-0"
                />
                <ViewToggle />
              </>
            )}
          </div>

          {total === 0 ? (
            <NoResults query={query} links={links} hidden={hidden} shopName={shopName} />
          ) : (
            <>
              <ResultList
                hits={result.hits}
                now={now}
                className="-mx-4 mt-3 md:mx-0 lg:data-[view=list]:overflow-hidden lg:data-[view=list]:rounded-card lg:data-[view=list]:border-x"
              />
              <Pagination offset={query.offset} total={total} links={links} />
            </>
          )}
        </div>
      </div>
    </Container>
  );
}

/** "Results for “esp32” in Shop A", with the shop removable. */
function Heading({
  query,
  raw,
  shopName,
}: {
  query: ResultsQuery;
  raw: RawParams;
  shopName?: string;
}) {
  const subject = query.q ? (
    <>Results for “{query.q}”</>
  ) : query.shop ? (
    <>Everything</>
  ) : (
    <>Results</>
  );
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h1 className="text-lg text-ink lg:text-xl">
        {subject}
        {shopName && <> in {shopName}</>}
      </h1>
      {query.shop && (
        <Link
          href={resultsLinks(PATHNAME, raw, query).clear("shop")}
          className="text-sm text-link underline-offset-2 hover:underline"
        >
          Search all shops
        </Link>
      )}
    </div>
  );
}

function NoResults({
  query,
  links,
  hidden,
  shopName,
}: {
  query: ResultsQuery;
  links: ReturnType<typeof resultsLinks>;
  hidden: number;
  shopName?: string;
}) {
  // Everything that matched is out of stock: say so, one click shows it.
  if (hidden > 0) {
    return (
      <div
        data-state="only-out-of-stock"
        className="mt-4 rounded-card border border-line bg-surface px-5 py-8"
      >
        <p className="font-display text-base font-bold text-ink">Nothing in stock</p>
        <p className="mt-1 text-sm text-ink-2">
          {plural(hidden, "product")} {hidden === 1 ? "matches" : "match"}, but no shop has{" "}
          {hidden === 1 ? "it" : "them"} in stock.
        </p>
        <Link
          href={links.showOutOfStock}
          className="mt-4 inline-flex h-11 items-center rounded-control bg-action px-4 text-sm font-semibold text-action-ink"
        >
          Show {formatCount(hidden)} out of stock
        </Link>
      </div>
    );
  }

  const removals: { label: string; href: string }[] = [];
  if (query.shop)
    removals.push({
      label: `Search all shops, not just ${shopName}`,
      href: links.clear("shop"),
    });
  if (query.minSuppliers)
    removals.push({
      label: "Remove “2+ shops”",
      href: links.clear("min_suppliers"),
    });
  if (query.category) removals.push({ label: "Any category", href: links.clear("category") });
  if (query.domain) removals.push({ label: "Every trade", href: links.clear("domain") });
  if (query.minPrice !== undefined || query.maxPrice !== undefined) {
    removals.push({
      label: "Any price",
      href: links.clear("min_price", "max_price"),
    });
  }

  return (
    <div
      data-state="no-results"
      className="mt-4 rounded-card border border-dashed border-line-strong px-5 py-10 text-center"
    >
      <p className="font-display text-base font-bold text-ink">Nothing matched</p>
      <p className="mt-1 text-sm text-ink-2">
        {activeFilterCount(query) > 0
          ? "Try without some of the filters."
          : "Try the part number on its own, or fewer words."}
      </p>
      {removals.length > 0 && (
        <ul className="mt-4 flex flex-wrap justify-center gap-2">
          {removals.map((removal) => (
            <li key={removal.href}>
              <Link
                href={removal.href}
                className="inline-flex h-11 items-center rounded-control border border-line-strong bg-surface px-4 text-sm text-ink hover:border-ink-3"
              >
                {removal.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Pagination({
  offset,
  total,
  links,
}: {
  offset: number;
  total: number;
  links: ReturnType<typeof resultsLinks>;
}) {
  if (total <= PAGE_SIZE && offset === 0) return null;
  const button =
    "flex h-11 items-center rounded-control border border-line-strong bg-surface px-4 text-ink hover:border-ink-3";
  return (
    <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-3 text-sm">
      {offset > 0 ? (
        <Link href={links.page(Math.max(0, offset - PAGE_SIZE))} rel="prev" className={button}>
          Previous
        </Link>
      ) : (
        <span />
      )}
      <span className="text-[13px] text-ink-3 tabular">
        {formatCount(Math.min(offset + 1, total))}–
        {formatCount(Math.min(offset + PAGE_SIZE, total))} of {formatCount(total)}
      </span>
      {offset + PAGE_SIZE < total ? (
        <Link href={links.page(offset + PAGE_SIZE)} rel="next" className={button}>
          Next
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}

/** "EGP 100 – 500", "EGP 100 and up", "Up to EGP 500". */
function priceLabel({ minPrice, maxPrice }: ResultsQuery): string {
  if (minPrice !== undefined && maxPrice !== undefined) return formatPriceRange(minPrice, maxPrice);
  if (minPrice !== undefined) return `${formatPriceRange(minPrice)} and up`;
  return `Up to ${formatPriceRange(maxPrice)}`;
}

/** /search with nothing to search: a prompt and the biggest trades. */
async function Landing() {
  const trades = tradesFrom(await fetchCategories().catch((): Category[] => [])).slice(0, 8);
  return (
    <Container className="py-8">
      <h1 className="text-xl text-ink">Search the catalogue</h1>
      <p className="mt-1 text-sm text-ink-2">
        Type a part number or a name in the search field above, or start from a trade.
      </p>
      {trades.length > 0 && (
        <ul className="mt-5 flex flex-wrap gap-2">
          {trades.map((trade) => (
            <li key={trade.domain}>
              <Link
                href={routes.trade(trade.domain)}
                className="inline-flex h-11 items-center gap-1.5 rounded-control border border-line bg-surface px-3 text-sm text-ink hover:border-line-strong"
              >
                {trade.label}
                <span className="text-ink-3 tabular">{formatCount(trade.count)}</span>
              </Link>
            </li>
          ))}
          <li>
            <Link
              href={routes.trades()}
              className="inline-flex h-11 items-center px-3 text-sm text-link underline-offset-2 hover:underline"
            >
              All trades
            </Link>
          </li>
        </ul>
      )}
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
