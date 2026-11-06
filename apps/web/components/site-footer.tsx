import { Link } from "@/components/link";

import { fetchStats } from "@/lib/api";
import { getDictionary, localeOf, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/** Closes every page with what makhzan is and, crucially, what it is not. */
export async function SiteFooter({ lang }: { lang: Lang }) {
  const t = getDictionary(lang);
  const locale = localeOf(lang);
  const stats = await fetchStats().catch(() => null);

  return (
    <footer className="mt-12 border-t-2 border-rule bg-surface">
      <div className="mx-auto flex max-w-6xl flex-wrap gap-x-12 gap-y-6 px-4 py-8 text-sm">
        <div className="flex flex-col gap-1">
          <span className="font-display text-xs tracking-widest text-ink uppercase">
            {t.footerCatalogue}
          </span>
          {stats && (
            <>
              <span data-numeric className="text-ink-muted">
                {stats.products.toLocaleString(locale)} {t.statProducts}
              </span>
              <span data-numeric className="text-ink-muted">
                {stats.suppliers.toLocaleString(locale)} {t.statSuppliers}
              </span>
            </>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <span className="font-display text-xs tracking-widest text-ink uppercase">
            {t.footerAbout}
          </span>
          <Link href={routes.search(lang)} className="text-ink-muted hover:text-ink">
            {t.browseAll}
          </Link>
          <Link href={`/${lang}/how-we-crawl`} className="text-ink-muted hover:text-ink">
            {t.freshness}
          </Link>
        </div>

        <div className="flex max-w-sm flex-col gap-2 text-ink-muted">
          <p>{t.handoffNote}</p>
          <p>
            {t.madeBy}{" "}
            <a href="https://merope.dev" className="underline hover:text-ink">
              Merope
            </a>
            .
          </p>
        </div>
      </div>
    </footer>
  );
}
