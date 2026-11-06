import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A plain GET form. No client state, no JS: submitting navigates to /search,
 * which is a real URL that can be shared, bookmarked and indexed.
 *
 * `compact` is the header's field; the default is the home page's big one,
 * which also gets a visible submit button.
 */
export function SearchField({
  defaultValue = "",
  placeholder = "Part number or name",
  compact = false,
  autoFocus = false,
  label = "Search",
  scope,
  className,
}: {
  defaultValue?: string;
  placeholder?: string;
  compact?: boolean;
  autoFocus?: boolean;
  /** The field's accessible name: "Search in Tools" for a scoped field. */
  label?: string;
  /** Parameters submitted with the query, e.g. `{ domain: "tools" }` for
   *  "Search in Tools". Hidden inputs, so scoping needs no JavaScript either. */
  scope?: Record<string, string>;
  className?: string;
}) {
  return (
    <form action="/search" method="get" role="search" className={cn("flex gap-2", className)}>
      {scope &&
        Object.entries(scope).map(([name, value]) => (
          <input key={name} type="hidden" name={name} value={value} />
        ))}
      <label
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 rounded-control border border-line-strong bg-ground px-3 focus-within:border-ink-3",
          compact ? "h-11" : "h-13",
        )}
      >
        <Search aria-hidden="true" className="size-[18px] shrink-0 text-ink-2" />
        <span className="sr-only">{label}</span>
        <input
          type="search"
          name="q"
          // `auto`: an Arabic query (they still work) types right to left.
          dir="auto"
          defaultValue={defaultValue}
          autoFocus={autoFocus}
          placeholder={placeholder}
          // 16px keeps iOS from zooming the page when the field takes focus.
          className="h-full min-w-0 flex-1 bg-transparent text-base text-ink outline-none placeholder:text-ink-3"
        />
      </label>
      <button
        type="submit"
        className={cn(
          "shrink-0 rounded-control bg-action px-5 font-semibold whitespace-nowrap text-action-ink",
          compact ? "sr-only" : "h-13 text-base",
        )}
      >
        Search
      </button>
    </form>
  );
}
