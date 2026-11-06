import { Link } from "@/components/link";

import type { Category } from "@/lib/api";
import { getDictionary, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * The only place the whole taxonomy appears at once. Sixteen verticals are too
 * many for a nav bar and too few to hide, so they live behind one control.
 *
 * A native <details>, so it opens without JavaScript and keyboard support comes
 * for free — this is chrome on every page and should not depend on hydration.
 */
export function BrowseMenu({ lang, verticals }: { lang: Lang; verticals: Vertical[] }) {
  const t = getDictionary(lang);
  return (
    <details className="group relative">
      <summary className="flex h-9 cursor-pointer list-none items-center gap-1.5 rounded-lg border border-rule bg-ground px-3 text-sm font-medium whitespace-nowrap [&::-webkit-details-marker]:hidden">
        {t.browse}
        <span aria-hidden="true" className="text-ink-muted transition-transform group-open:rotate-180">
          ▾
        </span>
      </summary>
      <div className="absolute start-0 top-full z-40 mt-2 max-h-[70svh] w-[min(92vw,30rem)] overflow-y-auto rounded-lg border-2 border-rule bg-surface p-2 shadow-lg">
        <ul className="grid grid-cols-2 gap-1">
          {verticals.map((vertical) => (
            <li key={vertical.domain}>
              <Link
                href={routes.vertical(lang, vertical.domain)}
                className="flex items-baseline justify-between gap-2 rounded-md px-2.5 py-2 text-sm hover:bg-chip"
              >
                <span>{vertical.label}</span>
                <span data-numeric className="text-xs text-ink-muted">
                  {vertical.count.toLocaleString(lang === "ar" ? "ar-EG" : "en")}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export type Vertical = { domain: string; label: string; count: number };

/**
 * Roll the flat category payload up into verticals. The API has no /domains
 * endpoint — a domain exists because categories belong to it — so the count is
 * the sum of its categories' product counts.
 */
export function verticalsFrom(categories: Category[], lang: Lang): Vertical[] {
  const totals = new Map<string, number>();
  for (const category of categories) {
    totals.set(category.domain, (totals.get(category.domain) ?? 0) + category.count);
  }
  return [...totals.entries()]
    .map(([domain, count]) => ({ domain, label: labelFor(domain, lang), count }))
    .sort((a, b) => b.count - a.count);
}

const AR_DOMAIN: Record<string, string> = {
  electronics: "إلكترونيات",
  tools: "عدد وأدوات",
  electrical: "كهرباء",
  "seals-bearings": "جوانات ورولمان بلي",
  piping: "مواسير وصمامات",
  machinery: "ماكينات",
  chemicals: "كيماويات",
  welding: "لحام",
  safety: "سلامة",
  timber: "أخشاب",
  garden: "حدائق",
  materials: "خامات",
  cleaning: "تنظيف",
  rigging: "رفع وتحميل",
  security: "أنظمة أمنية",
  automotive: "سيارات",
};

/** Domain slugs are not in the categories payload as display names, so they are
 *  titled here. Arabic is authored; English is derived from the slug. */
export function labelFor(domain: string, lang: Lang): string {
  if (lang === "ar" && AR_DOMAIN[domain]) return AR_DOMAIN[domain];
  return domain
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" & ");
}
