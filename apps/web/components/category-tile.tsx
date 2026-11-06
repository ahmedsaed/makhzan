import { Link } from "@/components/link";

import type { Category } from "@/lib/api";
import { categoryNameOf } from "@/lib/api";
import { localeOf, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * Tiles are for surveying — a few dozen categories being scanned — never for
 * products being compared. Two-up on phones, more as space allows; nothing is
 * hidden behind a "see all", because the long tail is what this catalogue is.
 */
export function CategoryTiles({
  categories,
  lang,
  eyebrowOf,
}: {
  categories: Category[];
  lang: Lang;
  eyebrowOf?: (category: Category) => string | null;
}) {
  const locale = localeOf(lang);
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {categories.map((category) => {
        const eyebrow = eyebrowOf?.(category);
        return (
          <li key={category.ref}>
            <Link
              href={routes.category(lang, category.ref)}
              className="flex h-full flex-col gap-0.5 rounded-lg border-2 border-rule bg-surface px-3 py-2.5 hover:border-ink-muted"
            >
              {eyebrow && (
                <span className="text-[9.5px] tracking-widest text-ink-muted uppercase">
                  {eyebrow}
                </span>
              )}
              <span className="font-display text-sm leading-tight font-bold text-ink">
                {categoryNameOf(category, lang)}
              </span>
              <span data-numeric className="text-[11.5px] text-ink-muted">
                {category.count.toLocaleString(locale)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
