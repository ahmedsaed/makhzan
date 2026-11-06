import { Link } from "@/components/link";
import { ThemeToggle } from "@/components/theme-toggle";
import { routes } from "@/lib/routes";

/**
 * The pages a supplier needs — how we crawl, and how to be removed, added or
 * corrected — on every page, because a shop owner can arrive anywhere.
 *
 * No data fetching, for the same reason as the header: it renders on error
 * pages and must not depend on the API.
 */
export function SiteFooter() {
  return (
    <footer className="mt-12 border-t border-line bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-6 text-sm md:px-6">
        <nav aria-label="About" className="flex flex-wrap items-center gap-x-5">
          <Link
            href={routes.forSuppliers()}
            className="flex h-11 items-center text-ink-2 hover:text-ink"
          >
            For suppliers
          </Link>
          <Link
            href={routes.howWeCrawl()}
            className="flex h-11 items-center text-ink-2 hover:text-ink"
          >
            How we crawl
          </Link>
        </nav>
        <ThemeToggle />
        <p className="text-ink-2 sm:ms-auto">
          Made by{" "}
          <a href="https://merope.dev" className="text-link underline">
            Merope
          </a>
        </p>
      </div>
    </footer>
  );
}
