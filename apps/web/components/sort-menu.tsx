import { Link } from "@/components/link";
import { withParams } from "@/lib/routes";

export const SORTS = [
  { value: "", label: "Best match" },
  { value: "price:asc", label: "Price, low first" },
  { value: "supplier_count:desc", label: "Most shops" },
  { value: "last_verified_at:desc", label: "Recently checked" },
] as const;

/**
 * The results sort, on any results page. A disclosure of links rather than a
 * <select>: each sort is a real URL, so it works without JavaScript and stays
 * shareable. `pathname` is the page's own path; the rest of its query is kept.
 */
export function SortMenu({
  pathname,
  params,
  current,
}: {
  pathname: string;
  params: Record<string, string | string[] | undefined>;
  current: string;
}) {
  const selected = SORTS.find((s) => s.value === current) ?? SORTS[0];
  return (
    <details className="relative ms-auto">
      <summary className="flex h-11 cursor-pointer list-none items-center rounded-md border border-line-strong bg-surface px-3 text-[13px] sm:h-9 [&::-webkit-details-marker]:hidden">
        Sort: {selected.label}
      </summary>
      <ul className="absolute end-0 z-30 mt-1 w-56 rounded-control border border-line bg-surface p-1">
        {SORTS.map((sort) => (
          <li key={sort.value}>
            <Link
              href={withParams(pathname, params, { sort: sort.value || null })}
              aria-current={sort.value === selected.value ? "true" : undefined}
              className="flex min-h-11 items-center rounded-md px-2.5 text-[13px] hover:bg-ground sm:min-h-9"
            >
              {sort.label}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}
