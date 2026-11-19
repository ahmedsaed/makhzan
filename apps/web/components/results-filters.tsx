import { CategoryIcon, hasCategoryIcons } from "@/components/category-icons";
import { DepartmentIcon } from "@/components/department-icon";
import { Link } from "@/components/link";
import {
  TREE_CHILDREN,
  TREE_CURRENT,
  TREE_LABEL,
  TREE_PANEL,
  treeCount,
  treeRow,
} from "@/components/tree-rows";
import { formatCount } from "@/lib/format";
import { withParams } from "@/lib/routes";
import { flatParams, type RawParams, type ResultsQuery } from "@/lib/results-query";
import { departmentLabel } from "@/lib/departments";
import { cn } from "@/lib/utils";

export type CategoryGroup = {
  domain: string;
  categories: { ref: string; count: number }[];
};

/** The parameters the price form owns; everything else rides along hidden. */
const PRICE_OWN = ["min_price", "max_price", "offset"];

/**
 * Category and price, the filters behind the "Category, price" chip: the
 * desktop rail beside the results, and the phone's bottom sheet. Rendered
 * twice by a results page, which is why nothing here has an id.
 *
 * The category list looks like the department pages' browse tree (layout B,
 * components/tree-rows.ts): in the rail, plain 36px rows in a bordered panel;
 * in the sheet, 44px tinted buttons. Each category is a link that picks it
 * (offset dropped, every other parameter kept), its department a heading over
 * it, and "Any category" clears the pick. The one in force is outlined, never
 * filled, and marked `aria-current="true"`: a filter that is on, not a place.
 * Counts are the results as they would be with that category picked.
 *
 * Price is a GET form with its own Clear, so all of it works with JavaScript
 * off. On a phone a category tap navigates at once, as in the browse sheet;
 * "Show results" applies the price.
 */
export function ResultsFilters({
  pathname,
  raw,
  query,
  groups,
  names,
  anyCount,
  variant,
}: {
  pathname: string;
  raw: RawParams;
  query: ResultsQuery;
  groups: CategoryGroup[];
  /** `ref` → display name, from GET /categories. */
  names: Map<string, string>;
  /** The count beside "Any category". */
  anyCount: number;
  /** The sheet gets phone-sized rows and a full-width button. */
  variant: "sheet" | "rail";
}) {
  const rail = variant === "rail";
  const density = rail ? "sidebar" : "sheet";
  const row = treeRow(density);
  const count = treeCount(density);
  const hidden = flatParams(raw, PRICE_OWN);
  const pick = (ref: string | null) => withParams(pathname, raw, { category: ref });
  const department = cn(
    "flex items-center gap-2.5 px-2.5 pt-2.5 pb-1 font-semibold text-ink-2",
    rail ? "text-xs" : "text-[13px]",
  );
  const label = cn(TREE_LABEL, !rail && "px-0");

  return (
    <div className="flex flex-col gap-4">
      {!rail && (
        <p className="text-[13px] text-ink-3">
          In stock, recently checked and 2+ shops are on the bar above the results.
        </p>
      )}

      <nav aria-label="Category" data-filter-categories={density}>
        <p className={label}>Category</p>
        <div className={cn(rail && TREE_PANEL)}>
          <ul role="list" className="flex flex-col gap-0.5">
            <li>
              <Link
                href={pick(null)}
                aria-current={query.category ? undefined : "true"}
                data-filter-category=""
                className={cn(row, !query.category && TREE_CURRENT)}
              >
                <span className="min-w-0 flex-1">Any category</span>
                <span className={count}>{formatCount(anyCount)}</span>
              </Link>
            </li>
            {groups.map((group) => {
              const drawn = hasCategoryIcons(group.domain);
              return (
                <li key={group.domain}>
                  <p className={department}>
                    <DepartmentIcon domain={group.domain} className="size-4 shrink-0 text-ink-3" />
                    {departmentLabel(group.domain)}
                  </p>
                  <ul role="list" className={TREE_CHILDREN}>
                    {group.categories.map((category) => {
                      const here = query.category === category.ref;
                      return (
                        <li key={category.ref}>
                          <Link
                            href={pick(category.ref)}
                            aria-current={here ? "true" : undefined}
                            data-filter-category={category.ref}
                            className={cn(row, here && TREE_CURRENT)}
                          >
                            {drawn && (
                              <CategoryIcon
                                iconRef={category.ref}
                                className="size-4 shrink-0 text-ink-2"
                              />
                            )}
                            <span className="min-w-0 flex-1 leading-snug">
                              {names.get(category.ref) ?? category.ref}
                            </span>
                            <span className={count}>{formatCount(category.count)}</span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </li>
              );
            })}
          </ul>
        </div>
      </nav>

      <form method="get" action={pathname} aria-label="Price" className="flex flex-col">
        {Object.entries(hidden).map(([key, value]) => (
          <input key={key} type="hidden" name={key} value={value} />
        ))}
        <p className={label}>Price, EGP</p>
        <div className={cn("flex flex-col gap-3", rail && cn(TREE_PANEL, "p-2.5"))}>
          <div className="flex gap-2.5">
            <PriceField
              label="Min"
              name="min_price"
              placeholder="0"
              value={query.minPrice}
              rail={rail}
            />
            <PriceField
              label="Max"
              name="max_price"
              placeholder="Any"
              value={query.maxPrice}
              rail={rail}
            />
          </div>
          {/* Clear is the price's own: "Any category" clears the category. */}
          <div className="flex gap-2.5">
            <Link
              href={withParams(pathname, raw, { min_price: null, max_price: null })}
              className={cn(
                "flex items-center rounded-control border border-line-strong bg-surface px-4 text-ink hover:border-ink-3",
                rail ? "h-9 text-sm" : "h-12 text-[15px]",
              )}
            >
              Clear
            </Link>
            <button
              type="submit"
              className={cn(
                "flex-1 rounded-control bg-action font-semibold text-action-ink",
                rail ? "h-9 text-sm" : "h-12 text-[15px]",
              )}
            >
              {rail ? "Apply" : "Show results"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function PriceField({
  label,
  name,
  placeholder,
  value,
  rail,
}: {
  label: string;
  name: string;
  placeholder: string;
  value: number | undefined;
  rail: boolean;
}) {
  return (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-[13px] text-ink-2 lg:text-xs">
      {label}
      <input
        type="number"
        name={name}
        min={0}
        step="any"
        inputMode="decimal"
        placeholder={placeholder}
        defaultValue={value}
        className={cn(
          "w-full min-w-0 rounded-md border border-line-strong bg-surface px-3 text-ink placeholder:text-ink-3",
          rail ? "h-9 text-sm" : "h-11 text-base",
        )}
      />
    </label>
  );
}
