import { FilterForm } from "@/components/filter-form";
import { Link } from "@/components/link";
import { formatCount } from "@/lib/format";
import { withParams } from "@/lib/routes";
import { flatParams, type RawParams, type ResultsQuery } from "@/lib/results-query";
import { departmentLabel } from "@/lib/departments";
import { cn } from "@/lib/utils";

export type CategoryGroup = {
  domain: string;
  categories: { ref: string; count: number }[];
};

/** The parameters this form owns; everything else rides along hidden. */
const OWN = ["category", "min_price", "max_price", "offset"];

/**
 * Category and price, the filters behind the "Category, price" chip: a GET
 * form, so it works with JavaScript off. Rendered twice by a results page —
 * in the phone sheet and in the desktop rail — which is why nothing here has
 * an id: each input sits inside its own label.
 *
 * Categories are radios grouped under their department, with the counts of the
 * results as they would be with that category picked.
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
  /** The sheet gets phone-sized rows and a full-width button; the rail picks
   *  a category the moment it is clicked. */
  variant: "sheet" | "rail";
}) {
  const rail = variant === "rail";
  const hidden = flatParams(raw, OWN);
  const row = cn(
    "flex cursor-pointer items-center gap-2.5 text-ink",
    rail ? "min-h-9 text-sm" : "min-h-11 text-[15px]",
  );
  const legend =
    "pb-1.5 font-sans text-xs font-semibold tracking-[0.06em] text-ink-2 uppercase lg:text-xs";

  return (
    <FilterForm action={pathname} autoSubmit={rail} className="flex flex-col gap-5">
      {Object.entries(hidden).map(([key, value]) => (
        <input key={key} type="hidden" name={key} value={value} />
      ))}

      {!rail && (
        <p className="-mb-2 text-[13px] text-ink-3">
          In stock, recently checked and 2+ shops are on the bar above the results.
        </p>
      )}

      <fieldset className="flex flex-col">
        <legend className={legend}>Category</legend>
        <label className={row}>
          <input
            type="radio"
            name="category"
            value=""
            defaultChecked={!query.category}
            className="size-[18px] accent-action"
          />
          <span className="flex-1">Any category</span>
          <span className="text-ink-3 tabular">{formatCount(anyCount)}</span>
        </label>
        {groups.map((group) => (
          <div key={group.domain} className="flex flex-col">
            <span className="pt-2 pb-0.5 text-xs text-ink-3">{departmentLabel(group.domain)}</span>
            {group.categories.map((category) => (
              <label key={category.ref} className={cn(row, "ps-3")}>
                <input
                  type="radio"
                  name="category"
                  value={category.ref}
                  defaultChecked={query.category === category.ref}
                  className="size-[18px] shrink-0 accent-action"
                />
                <span className="min-w-0 flex-1">{names.get(category.ref) ?? category.ref}</span>
                <span className="text-ink-3 tabular">{formatCount(category.count)}</span>
              </label>
            ))}
          </div>
        ))}
      </fieldset>

      <fieldset className="flex flex-col">
        <legend className={legend}>Price, EGP</legend>
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
      </fieldset>

      <div
        className={cn(
          "flex gap-2.5",
          !rail && "sticky bottom-0 -mx-4 -mb-4 border-t border-line bg-surface px-4 pt-3 pb-5",
        )}
      >
        <Link
          href={withParams(pathname, raw, {
            category: null,
            min_price: null,
            max_price: null,
          })}
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
    </FilterForm>
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
