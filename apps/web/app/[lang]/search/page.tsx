import type { Metadata } from "next";
import { Link } from "@/components/link";
import { notFound } from "next/navigation";

import { FacetRail } from "@/components/facet-rail";
import { ProductRows, rowFromHit } from "@/components/product-row";
import { Container, Empty } from "@/components/section";
import { fetchCategories, searchProducts } from "@/lib/api";
import { getDictionary, isLang, localeOf, type Lang } from "@/lib/i18n";
import { routes, type SearchQuery } from "@/lib/routes";

const PAGE_SIZE = 24;

const SORTS = [
  { value: "", key: "sortRelevance" },
  { value: "price:asc", key: "sortPriceAsc" },
  { value: "price:desc", key: "sortPriceDesc" },
  { value: "supplier_count:desc", key: "sortSuppliers" },
  { value: "last_verified_at:desc", key: "sortVerified" },
] as const;

type RawParams = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** URL → the query this page ran. The URL is the only state; nothing is held
 *  in a component. */
function queryFrom(params: RawParams): SearchQuery {
  const offset = Number.parseInt(one(params.offset) ?? "", 10);
  return {
    q: one(params.q) ?? "",
    category: one(params.category),
    domain: one(params.domain),
    inStock: one(params.in_stock) === "true",
    sort: one(params.sort),
    offset: Number.isFinite(offset) && offset > 0 ? offset : undefined,
  };
}

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<{ lang: string }>;
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { lang } = await params;
  if (!isLang(lang)) return {};
  const q = one((await searchParams).q) ?? "";
  const t = getDictionary(lang);
  return {
    title: q ? `${q} — ${t.searchAction}` : t.searchAction,
    // A filtered result set is not a page worth indexing on its own; the
    // canonical browse surfaces are the category pages.
    robots: { index: false, follow: true },
  };
}

export default async function SearchPage({
  params,
  searchParams,
}: {
  params: Promise<{ lang: string }>;
  searchParams: Promise<RawParams>;
}) {
  const { lang } = await params;
  if (!isLang(lang)) notFound();
  const typed: Lang = lang;
  const t = getDictionary(typed);
  const locale = localeOf(typed);

  const query = queryFrom(await searchParams);
  const [result, categories] = await Promise.all([
    searchProducts({ ...query, facets: true, limit: PAGE_SIZE }),
    fetchCategories().catch(() => []),
  ]);

  const total = result.total ?? 0;
  const offset = query.offset ?? 0;
  const rows = result.hits.map((hit) => rowFromHit(hit, typed));
  const rail = (
    <FacetRail lang={typed} query={query} facets={result.facets} categories={categories} />
  );

  const active: { label: string; href: string }[] = [];
  if (query.domain) {
    active.push({
      label: query.domain,
      href: routes.search(typed, { ...query, domain: undefined, offset: undefined }),
    });
  }
  if (query.category) {
    const category = categories.find((c) => c.ref === query.category);
    active.push({
      label: category ? (typed === "ar" && category.name_ar) || category.name_en : query.category,
      href: routes.search(typed, { ...query, category: undefined, offset: undefined }),
    });
  }
  if (query.inStock) {
    active.push({
      label: t.inStockOnly,
      href: routes.search(typed, { ...query, inStock: undefined, offset: undefined }),
    });
  }

  return (
    <Container className="py-6">
      {/* Says why the ordering changed, instead of leaving it mysterious. */}
      {result.identifier_query && (
        <p className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border-2 border-accent bg-surface px-3 py-2 text-[12.5px] text-ink-muted">
          <span data-identifier className="font-mono text-xs text-accent">
            {result.query}
          </span>
          {t.identifierBand}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[13rem_1fr]">
        <aside className="hidden lg:block">{rail}</aside>

        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[12.5px] text-ink-muted">
              <strong data-numeric className="font-mono text-ink">
                {total.toLocaleString(locale)}
              </strong>{" "}
              {t.results}
            </p>
            <SortMenu lang={typed} query={query} />
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            {/* The filters sheet, phone only. Active filters stay visible beside
                it so a result count is never unexplained. */}
            <details className="lg:hidden">
              <summary className="cursor-pointer list-none rounded-lg border border-rule bg-surface px-3 py-1.5 text-xs font-medium [&::-webkit-details-marker]:hidden">
                {t.filters}
                {active.length > 0 && ` (${active.length})`}
              </summary>
              <div className="mt-2 rounded-lg border-2 border-rule bg-surface p-3">{rail}</div>
            </details>

            {active.map((chip) => (
              <Link
                key={chip.href}
                href={chip.href}
                className="rounded-lg border border-accent px-2.5 py-1 text-xs font-semibold text-accent"
              >
                {chip.label} ✕
              </Link>
            ))}
            {active.length > 0 && (
              <Link
                href={routes.search(typed, { q: query.q })}
                className="text-xs text-ink-muted underline"
              >
                {t.clearAll}
              </Link>
            )}
          </div>

          {rows.length === 0 ? (
            <div className="mt-6">
              <Empty title={t.noResults} hint={t.noResultsHint} />
            </div>
          ) : (
            <div className="mt-3">
              <ProductRows rows={rows} lang={typed} />
            </div>
          )}

          <nav className="mt-5 flex items-center justify-between gap-3 text-sm">
            {offset > 0 ? (
              <Link
                href={routes.search(typed, {
                  ...query,
                  offset: Math.max(0, offset - PAGE_SIZE) || undefined,
                })}
                className="rounded-lg border border-rule px-3 py-1.5 hover:bg-chip"
              >
                ←
              </Link>
            ) : (
              <span />
            )}
            {offset + PAGE_SIZE < total && (
              <Link
                href={routes.search(typed, { ...query, offset: offset + PAGE_SIZE })}
                className="rounded-lg border border-rule px-3 py-1.5 hover:bg-chip"
              >
                →
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
function SortMenu({ lang, query }: { lang: Lang; query: SearchQuery }) {
  const t = getDictionary(lang);
  const current = SORTS.find((s) => s.value === (query.sort ?? "")) ?? SORTS[0];
  return (
    <details className="relative">
      <summary className="cursor-pointer list-none rounded-lg border border-rule bg-surface px-3 py-1.5 text-xs [&::-webkit-details-marker]:hidden">
        {t.sort}: {t[current.key]}
      </summary>
      <ul className="absolute end-0 z-30 mt-1 w-56 rounded-lg border-2 border-rule bg-surface p-1 shadow-lg">
        {SORTS.map((sort) => (
          <li key={sort.value}>
            <Link
              href={routes.search(lang, {
                ...query,
                sort: sort.value || undefined,
                offset: undefined,
              })}
              className="block rounded-md px-2.5 py-1.5 text-xs hover:bg-chip"
            >
              {t[sort.key]}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to, and prerendering 57,000 products would be pointless
 * anyway. SSR still gives crawlers complete HTML — the caching that matters
 * happens in the fetch layer (see lib/api.ts), not in the page shell.
 */
export const dynamic = "force-dynamic";
