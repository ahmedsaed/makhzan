import { Suspense } from "react";

import { HeaderSearch } from "@/components/header-search";
import { Link } from "@/components/link";
import { SearchField } from "@/components/search-field";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * Wordmark, search, and the two ways to browse.
 *
 * Phones get two rows — wordmark and nav, then search full width — and from
 * `md` it is one row. Search stays visible at every width: collapsing it behind
 * a magnifier to save 44px is the wrong trade on a site whose job is search.
 *
 * `search={false}` is for the home page, which leads with its own large field;
 * two search boxes on one screen ask the visitor to choose between them.
 *
 * No data fetching, so it renders the same on error and 404 pages, and cannot
 * take a page down with it when the API is unreachable.
 */
export function SiteHeader({ search = true }: { search?: boolean }) {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2.5 px-4 py-2.5 md:flex-nowrap md:px-6">
        <Link
          href={routes.home()}
          className="flex h-11 shrink-0 items-center font-display text-[22px] font-bold tracking-[-0.02em] text-ink"
        >
          makhzan
        </Link>

        {search && (
          // The fallback is the same field without the current query: the
          // header must never render without its search, even for a moment.
          <Suspense
            fallback={
              <SearchField
                compact
                className="order-last w-full md:order-none md:max-w-xl md:flex-1"
              />
            }
          >
            <HeaderSearch className="order-last w-full md:order-none md:max-w-xl md:flex-1" />
          </Suspense>
        )}

        <nav aria-label="Site" className="ms-auto flex items-center gap-1 text-sm">
          <NavLink href={routes.trades()}>Trades</NavLink>
          <NavLink href={routes.shops()}>Shops</NavLink>
          <NavLink href={routes.howWeCrawl()} className="hidden md:flex">
            How we crawl
          </NavLink>
        </nav>
      </div>
    </header>
  );
}

function NavLink({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex h-11 items-center px-2.5 whitespace-nowrap text-ink-2 hover:text-ink",
        className,
      )}
    >
      {children}
    </Link>
  );
}
