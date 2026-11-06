import { Suspense } from "react";
import { Link } from "@/components/link";

import { BrowseMenu, verticalsFrom } from "@/components/browse-menu";
import { LangSwitch } from "@/components/lang-switch";
import { ThemeToggle } from "@/components/theme-toggle";
import { SearchField } from "@/components/search-field";
import { fetchCategories } from "@/lib/api";
import { getDictionary, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * Two rows on phones — logo, browse and the toggles, then search full width —
 * and one row from `md`. Search stays visible at every width: collapsing it
 * behind a magnifier to save 40px is the wrong trade on a site whose only job
 * is search.
 */
export async function SiteHeader({ lang }: { lang: Lang }) {
  const t = getDictionary(lang);
  // Chrome must not take the page down with it if the API is unreachable.
  const verticals = await fetchCategories()
    .then((categories) => verticalsFrom(categories, lang))
    .catch(() => []);

  return (
    <header className="sticky top-0 z-30 border-b-2 border-rule bg-surface">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5">
        <Link
          href={routes.home(lang)}
          className="flex h-9 shrink-0 items-center font-display text-lg font-bold tracking-tight text-ink"
        >
          {t.brand}
          <span className="text-accent">.</span>
        </Link>

        {verticals.length > 0 && <BrowseMenu lang={lang} verticals={verticals} />}

        <SearchField
          lang={lang}
          className="order-3 w-full md:order-none md:w-auto md:flex-1"
          placeholder={t.searchPlaceholder}
        />

        <div className="ms-auto flex items-center gap-1.5 md:ms-0">
          <Suspense fallback={<span className="h-9 w-9" />}>
            <LangSwitch lang={lang} />
          </Suspense>
          <ThemeToggle label={t.theme} />
        </div>
      </div>
    </header>
  );
}
