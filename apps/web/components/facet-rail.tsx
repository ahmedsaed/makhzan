import { Link } from "@/components/link";

import { labelFor } from "@/components/browse-menu";
import type { Category, Facets } from "@/lib/api";
import { categoryNameOf } from "@/lib/api";
import { getDictionary, localeOf, type Lang } from "@/lib/i18n";
import { routes, type SearchQuery } from "@/lib/routes";

/**
 * Facets as links, not checkboxes.
 *
 * Every narrowing produces a new URL, so a filtered result set can be shared and
 * indexed, the back button works, and none of it needs JavaScript. Counts come
 * from the engine over the whole matching set, not the page on screen.
 */
export function FacetRail({
  lang,
  query,
  facets,
  categories,
}: {
  lang: Lang;
  query: SearchQuery;
  facets: Facets | undefined;
  categories: Category[];
}) {
  const t = getDictionary(lang);
  const locale = localeOf(lang);
  const byRef = new Map(categories.map((category) => [category.ref, category]));

  const domains = Object.entries(facets?.domain ?? {}).sort((a, b) => b[1] - a[1]);
  const refs = Object.entries(facets?.category_ref ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12);

  // Paging is meaningless once the filters change, so every facet link drops it.
  const base: SearchQuery = { ...query, offset: undefined };

  return (
    <div className="flex flex-col gap-5 text-sm">
      {domains.length > 0 && (
        <FacetGroup title={t.facetTrade}>
          {domains.map(([domain, count]) => (
            <FacetLink
              key={domain}
              href={routes.search(lang, {
                ...base,
                domain: query.domain === domain ? undefined : domain,
              })}
              label={labelFor(domain, lang)}
              count={count.toLocaleString(locale)}
              active={query.domain === domain}
            />
          ))}
        </FacetGroup>
      )}

      {refs.length > 0 && (
        <FacetGroup title={t.facetCategory}>
          {refs.map(([ref, count]) => {
            const category = byRef.get(ref);
            return (
              <FacetLink
                key={ref}
                href={routes.search(lang, {
                  ...base,
                  category: query.category === ref ? undefined : ref,
                })}
                label={category ? categoryNameOf(category, lang) : ref}
                count={count.toLocaleString(locale)}
                active={query.category === ref}
              />
            );
          })}
        </FacetGroup>
      )}

      <FacetGroup title={t.facetAvailability}>
        <FacetLink
          href={routes.search(lang, { ...base, inStock: query.inStock ? undefined : true })}
          label={t.inStockOnly}
          active={Boolean(query.inStock)}
        />
      </FacetGroup>
    </div>
  );
}

function FacetGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 font-display text-[11px] tracking-widest text-ink-muted uppercase">
        {title}
      </h3>
      <ul>{children}</ul>
    </div>
  );
}

function FacetLink({
  href,
  label,
  count,
  active,
}: {
  href: string;
  label: string;
  count?: string;
  active: boolean;
}) {
  return (
    <li>
      <Link
        href={href}
        aria-current={active ? "true" : undefined}
        className={`flex items-center justify-between gap-2 rounded-md px-2 py-1.5 ${
          active ? "font-semibold text-ink" : "text-ink-muted hover:bg-chip hover:text-ink"
        }`}
      >
        <span className="truncate">
          {active && <span className="me-1 text-accent">▸</span>}
          {label}
        </span>
        {count && (
          <span data-numeric className="text-xs">
            {count}
          </span>
        )}
      </Link>
    </li>
  );
}
