import type { Metadata } from "next";

import { Link } from "@/components/link";
import { NotAnswering, Results } from "@/components/results";
import { Container } from "@/components/section";
import { categoryNameOf, fetchCategories, fetchSupplier, type Category } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import {
  fetchResults,
  parseResultsQuery,
  resultsLinks,
  topCategories,
  type RawParams,
  type ResultsQuery,
} from "@/lib/results-query";
import { departmentLabel, departmentsFrom } from "@/lib/departments";

const PATHNAME = "/search";

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { q } = parseResultsQuery(await searchParams);
  // A filtered result set is not a page worth indexing on its own; the
  // canonical browse surfaces are the department and category pages. No canonical
  // either: a query is not a page.
  return pageMetadata({ title: q || "Search", noindex: true });
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

  const [data, categories, shop] = await Promise.all([
    fetchResults(query),
    fetchCategories().catch((): Category[] => []),
    query.shop ? fetchSupplier(query.shop).catch(() => null) : null,
  ]);
  const { result } = data;

  const shopName = query.shop ? (shop?.name ?? query.shop) : undefined;
  const heading = <Heading query={query} raw={raw} shopName={shopName} />;

  if (!result) {
    return (
      <Container className="py-5">
        {heading}
        <NotAnswering className="mt-4" />
      </Container>
    );
  }

  const links = resultsLinks(PATHNAME, raw, query);
  const names = new Map(categories.map((c) => [c.ref, categoryNameOf(c)]));
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

      <Results
        className="mt-3"
        pathname={PATHNAME}
        raw={raw}
        query={query}
        data={{ ...data, result }}
        names={names}
        shopName={shopName}
        top={
          top.length > 0 && (
            <section aria-labelledby="top-categories" className="flex flex-col gap-2">
              <h2 id="top-categories" className="font-sans text-[13px] font-semibold text-ink-2">
                Top categories for “{query.q}”
              </h2>
              <ul className="-mx-4 flex [scrollbar-width:none] gap-2 overflow-x-auto px-4 md:mx-0 md:flex-wrap md:px-0">
                {top.map(({ ref, count }) => (
                  <li key={ref} className="shrink-0">
                    <Link
                      href={links.category(ref)}
                      className="flex min-h-11 flex-col gap-0.5 rounded-control border border-line bg-surface px-3 py-2 text-ink hover:border-line-strong"
                    >
                      <span className="text-xs text-ink-3">{departmentLabel(ref.split(":")[0])} ›</span>
                      <span className="text-sm font-semibold">
                        {names.get(ref) ?? ref}{" "}
                        <span className="font-normal text-ink-3 tabular">{formatCount(count)}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )
        }
      />
    </Container>
  );
}

/**
 * "Results for “esp32” in Shop A"; with no query, "Everything in Shop A" or
 * "Everything in Tools". The shop is removable.
 */
function Heading({
  query,
  raw,
  shopName,
}: {
  query: ResultsQuery;
  raw: RawParams;
  shopName?: string;
}) {
  const scope = shopName ?? (query.domain ? departmentLabel(query.domain) : undefined);
  const subject = query.q ? <>Results for “{query.q}”</> : scope ? <>Everything</> : <>Results</>;
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h1 className="text-lg text-ink lg:text-xl">
        {subject}
        {scope && <> in {scope}</>}
      </h1>
      {query.shop && (
        <Link
          href={resultsLinks(PATHNAME, raw, query).clear("shop")}
          className="inline-flex min-h-11 items-center text-sm text-link underline-offset-2 hover:underline"
        >
          Search all shops
        </Link>
      )}
    </div>
  );
}

/** /search with nothing to search: a prompt and the biggest departments. */
async function Landing() {
  const departments = departmentsFrom(await fetchCategories().catch((): Category[] => [])).slice(0, 8);
  return (
    <Container className="py-8">
      <h1 className="text-xl text-ink">Search the catalogue</h1>
      <p className="mt-1 text-sm text-ink-2">
        Type a part number or a name in the search field above, or start from a department.
      </p>
      {departments.length > 0 && (
        <ul className="mt-5 flex flex-wrap gap-2">
          {departments.map((department) => (
            <li key={department.domain}>
              <Link
                href={routes.department(department.domain)}
                className="inline-flex h-11 items-center gap-1.5 rounded-control border border-line bg-surface px-3 text-sm text-ink hover:border-line-strong"
              >
                {department.label}
                <span className="text-ink-3 tabular">{formatCount(department.count)}</span>
              </Link>
            </li>
          ))}
          <li>
            <Link
              href={routes.departments()}
              className="inline-flex h-11 items-center px-3 text-sm text-link underline-offset-2 hover:underline"
            >
              All departments
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
