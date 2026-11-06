"use client";

import { useRouter } from "next/navigation";

import { withParams } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * The sort order as a GET form: a `<select>` and, with JavaScript off, a
 * button to submit it. With JavaScript the choice navigates as soon as it is
 * made, building the URL itself so "Best match" leaves no empty `sort=`.
 *
 * `params` is the current URL's query; everything but the sort and the page is
 * carried through as hidden fields, so sorting never drops a filter.
 */
export function SortSelect({
  pathname,
  params,
  options,
  current = "",
  className,
}: {
  pathname: string;
  params: Record<string, string>;
  options: readonly { value: string; label: string }[];
  current?: string;
  className?: string;
}) {
  const router = useRouter();
  const kept = Object.entries(params).filter(([key]) => key !== "sort" && key !== "offset");

  return (
    <form action={pathname} method="get" className={cn("flex items-center gap-2", className)}>
      {kept.map(([key, value]) => (
        <input key={key} type="hidden" name={key} value={value} />
      ))}
      <label className="flex items-center gap-2 text-[13px] text-ink-2 lg:text-sm">
        <span className="sr-only lg:not-sr-only">Sort</span>
        <select
          name="sort"
          defaultValue={current}
          onChange={(event) =>
            router.push(withParams(pathname, params, { sort: event.target.value || null }))
          }
          className="h-11 rounded-md border border-line-strong bg-surface px-2 text-[13px] text-ink sm:h-9 lg:text-sm"
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <noscript>
        <button
          type="submit"
          className="h-11 rounded-md border border-line-strong bg-surface px-3 text-[13px] text-ink sm:h-9"
        >
          Sort
        </button>
      </noscript>
    </form>
  );
}
