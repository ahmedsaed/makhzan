import { getDictionary, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/**
 * A plain GET form. No client state, no JS: submitting navigates to the search
 * route, which is a real URL that can be shared, bookmarked and indexed.
 */
export function SearchField({
  lang,
  defaultValue = "",
  placeholder,
  className,
  autoFocus = false,
}: {
  lang: Lang;
  defaultValue?: string;
  placeholder?: string;
  className?: string;
  autoFocus?: boolean;
}) {
  const t = getDictionary(lang);
  return (
    <form action={`/${lang}/search`} method="get" role="search" className={cn("flex gap-2", className)}>
      <input
        type="search"
        name="q"
        dir="auto"
        defaultValue={defaultValue}
        autoFocus={autoFocus}
        aria-label={t.searchAction}
        placeholder={placeholder ?? t.searchPlaceholder}
        className="h-9 min-w-0 flex-1 rounded-lg border border-rule bg-ground px-3 text-sm text-ink placeholder:text-ink-muted"
      />
      <button
        type="submit"
        className="h-9 shrink-0 rounded-lg border border-accent bg-accent px-4 text-sm font-semibold whitespace-nowrap text-accent-ink"
      >
        {t.searchAction}
      </button>
    </form>
  );
}
