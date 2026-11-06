import type { Metadata } from "next";
import { Link } from "@/components/link";
import { notFound } from "next/navigation";

import { labelFor } from "@/components/browse-menu";
import { ProductRows, rowFromHit } from "@/components/product-row";
import { Container, Empty } from "@/components/section";
import { categoryNameOf, fetchCategories, searchProducts } from "@/lib/api";
import { getDictionary, isLang, localeOf } from "@/lib/i18n";
import { joinRef, routes } from "@/lib/routes";

const PAGE_SIZE = 24;

/**
 * Browsing one category. The same query search runs, with `category` pinned and
 * the rail scoped to this vertical — browse is the surface that *is* scoped to a
 * domain, unlike search.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string; domain: string; slug: string }>;
}): Promise<Metadata> {
  const { lang, domain, slug } = await params;
  if (!isLang(lang)) return {};
  const categories = await fetchCategories(domain).catch(() => []);
  const category = categories.find((c) => c.slug === slug);
  return {
    title: category ? categoryNameOf(category, lang) : slug,
    alternates: {
      canonical: `/${lang}/browse/${domain}/${slug}`,
      languages: { en: `/en/browse/${domain}/${slug}`, ar: `/ar/browse/${domain}/${slug}` },
    },
  };
}

export default async function CategoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ lang: string; domain: string; slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { lang, domain, slug } = await params;
  if (!isLang(lang)) notFound();
  const t = getDictionary(lang);
  const locale = localeOf(lang);

  const raw = await searchParams;
  const offsetRaw = Number.parseInt(
    (Array.isArray(raw.offset) ? raw.offset[0] : raw.offset) ?? "",
    10,
  );
  const offset = Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : 0;

  const ref = joinRef(domain, slug);
  const categories = await fetchCategories(domain);
  const category = categories.find((c) => c.ref === ref);
  if (!category) notFound();

  const result = await searchProducts({
    category: ref,
    domain,
    limit: PAGE_SIZE,
    offset,
  });

  const siblings = categories
    .filter((c) => c.parent === category.parent && c.count > 0)
    .sort((a, b) => b.count - a.count);
  const total = result.total ?? 0;

  return (
    <Container className="py-6">
      <nav className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
        <Link href={routes.vertical(lang, domain)} className="hover:text-ink">
          {labelFor(domain, lang)}
        </Link>
        <span>›</span>
        <span className="text-ink">{categoryNameOf(category, lang)}</span>
      </nav>

      <h1 className="mb-1 text-2xl">{categoryNameOf(category, lang)}</h1>
      <p className="mb-5 text-[12.5px] text-ink-muted">
        <strong data-numeric className="font-mono text-ink">
          {total.toLocaleString(locale)}
        </strong>{" "}
        {t.results}
      </p>

      <div className="grid gap-6 lg:grid-cols-[13rem_1fr]">
        <aside className="hidden lg:block">
          <h2 className="mb-1.5 font-display text-[11px] tracking-widest text-ink-muted uppercase">
            {t.facetCategory}
          </h2>
          <ul className="text-sm">
            {siblings.map((sibling) => (
              <li key={sibling.ref}>
                <Link
                  href={routes.category(lang, sibling.ref)}
                  aria-current={sibling.ref === ref ? "true" : undefined}
                  className={`flex items-center justify-between gap-2 rounded-md px-2 py-1.5 ${
                    sibling.ref === ref
                      ? "font-semibold text-ink"
                      : "text-ink-muted hover:bg-chip hover:text-ink"
                  }`}
                >
                  <span className="truncate">{categoryNameOf(sibling, lang)}</span>
                  <span data-numeric className="text-xs">
                    {sibling.count.toLocaleString(locale)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </aside>

        <div>
          {result.hits.length === 0 ? (
            <Empty title={t.noResults} hint={t.noResultsHint} />
          ) : (
            <ProductRows rows={result.hits.map((hit) => rowFromHit(hit, lang))} lang={lang} />
          )}

          <nav className="mt-5 flex items-center justify-between gap-3 text-sm">
            {offset > 0 ? (
              <Link
                href={`${routes.category(lang, ref)}?offset=${Math.max(0, offset - PAGE_SIZE)}`}
                className="rounded-lg border border-rule px-3 py-1.5 hover:bg-chip"
              >
                ←
              </Link>
            ) : (
              <span />
            )}
            {offset + PAGE_SIZE < total && (
              <Link
                href={`${routes.category(lang, ref)}?offset=${offset + PAGE_SIZE}`}
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

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to, and prerendering 57,000 products would be pointless
 * anyway. SSR still gives crawlers complete HTML — the caching that matters
 * happens in the fetch layer (see lib/api.ts), not in the page shell.
 */
export const dynamic = "force-dynamic";
