import { Link } from "@/components/link";
import type { Category, Facets } from "@/lib/api";
import { categoryNameOf } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { routes, type SearchQuery } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";
import { cn } from "@/lib/utils";

/**
 * Facets as links, not checkboxes.
 *
 * Every narrowing produces a new URL, so a filtered result set can be shared and
 * indexed, the back button works, and none of it needs JavaScript. Counts come
 * from the engine over the whole matching set, not the page on screen.
 */
export function FacetRail({
  query,
  facets,
  categories,
}: {
  query: SearchQuery;
  facets: Facets | undefined;
  categories: Category[];
}) {
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
        <FacetGroup title="Trade">
          {domains.map(([domain, count]) => (
            <FacetLink
              key={domain}
              href={routes.search({
                ...base,
                domain: query.domain === domain ? undefined : domain,
              })}
              label={tradeLabel(domain)}
              count={formatCount(count)}
              active={query.domain === domain}
            />
          ))}
        </FacetGroup>
      )}

      {refs.length > 0 && (
        <FacetGroup title="Category">
          {refs.map(([ref, count]) => {
            const category = byRef.get(ref);
            return (
              <FacetLink
                key={ref}
                href={routes.search({
                  ...base,
                  category: query.category === ref ? undefined : ref,
                })}
                label={category ? categoryNameOf(category) : ref}
                count={formatCount(count)}
                active={query.category === ref}
              />
            );
          })}
        </FacetGroup>
      )}
    </div>
  );
}

function FacetGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1.5 font-sans text-xs font-semibold tracking-[0.06em] text-ink-2 uppercase">
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
        className={cn(
          "flex min-h-11 items-center justify-between gap-2 rounded-md px-2 lg:min-h-9",
          active ? "font-semibold text-ink" : "text-ink-2 hover:bg-ground hover:text-ink",
        )}
      >
        <span className="truncate">{label}</span>
        {count && <span className="tabular text-xs text-ink-3">{count}</span>}
      </Link>
    </li>
  );
}
