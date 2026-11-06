import { notFound } from "next/navigation";
import { Link } from "@/components/link";

import { ProductRows, rowFromHit } from "@/components/product-row";
import { SearchField } from "@/components/search-field";
import { Container, SectionHeading } from "@/components/section";
import { labelFor } from "@/components/browse-menu";
import { fetchCategories, fetchStats, searchProducts } from "@/lib/api";
import { getDictionary, isLang, localeOf } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * Two jobs: take a query from someone who knows what they want, and show the
 * shape of the catalogue to someone who doesn't.
 *
 * The multi-supplier rail is the one thing no supplier's own site can show, and
 * it is the reason makhzan exists — so it is on the homepage rather than buried.
 */
export default async function HomePage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  if (!isLang(lang)) notFound();
  const t = getDictionary(lang);
  const locale = localeOf(lang);

  const [categories, stats, multi] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchStats().catch(() => null),
    searchProducts({ minSuppliers: 2, sort: "supplier_count:desc", limit: 6 }).catch(() => null),
  ]);

  // Verticals, largest first. A domain exists because categories belong to it,
  // so its size is the sum of theirs.
  const totals = new Map<string, number>();
  for (const category of categories) {
    totals.set(category.domain, (totals.get(category.domain) ?? 0) + category.count);
  }
  const verticals = [...totals.entries()].sort((a, b) => b[1] - a[1]);

  return (
    <>
      <section className="border-b border-rule bg-surface">
        <Container className="flex flex-col items-center gap-5 py-12 text-center sm:py-16">
          <h1 className="max-w-[22ch] text-2xl leading-tight sm:text-4xl">{t.tagline}</h1>
          <SearchField
            lang={lang}
            autoFocus
            placeholder={t.searchExamples}
            className="w-full max-w-xl"
          />
          {stats && (
            <p className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-sm text-ink-muted">
              <span>
                <strong data-numeric className="font-mono text-ink">
                  {stats.products.toLocaleString(locale)}
                </strong>{" "}
                {t.statProducts}
              </span>
              <span>
                <strong data-numeric className="font-mono text-ink">
                  {stats.suppliers.toLocaleString(locale)}
                </strong>{" "}
                {t.statSuppliers}
              </span>
              <span>
                <strong data-numeric className="font-mono text-ink">
                  {verticals.length.toLocaleString(locale)}
                </strong>{" "}
                {t.statVerticals}
              </span>
            </p>
          )}
        </Container>
      </section>

      <Container className="py-8">
        <SectionHeading>{t.byTrade}</SectionHeading>
        {/* All of them. Hiding half the catalogue behind "see all" is how a
            directory loses the long tail it worked hardest to build. */}
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {verticals.map(([domain, count]) => (
            <li key={domain}>
              <Link
                href={routes.vertical(lang, domain)}
                className="flex h-full flex-col gap-0.5 rounded-lg border-2 border-rule bg-surface px-3 py-2.5 hover:border-ink-muted"
              >
                <span className="font-display text-sm leading-tight font-bold text-ink">
                  {labelFor(domain, lang)}
                </span>
                <span data-numeric className="text-[11.5px] text-ink-muted">
                  {count.toLocaleString(locale)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Container>

      {multi && multi.hits.length > 0 && (
        <Container className="pb-12">
          <SectionHeading>{t.multiSupplier}</SectionHeading>
          <p className="-mt-2 mb-3 text-sm text-ink-muted">{t.multiSupplierLead}</p>
          <ProductRows rows={multi.hits.map((hit) => rowFromHit(hit, lang))} lang={lang} />
        </Container>
      )}
    </>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to, and prerendering 57,000 products would be pointless
 * anyway. SSR still gives crawlers complete HTML — the caching that matters
 * happens in the fetch layer (see lib/api.ts), not in the page shell.
 */
export const dynamic = "force-dynamic";
