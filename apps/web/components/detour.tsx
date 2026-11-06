import { Link } from "@/components/link";
import { SearchField } from "@/components/search-field";
import { routes } from "@/lib/routes";

/**
 * Where to go from a page that is not there: a search, and the ways to browse.
 * Shared by the 404 and error pages, which must not fetch anything — they are
 * what renders when the catalogue is the thing that broke.
 */
export function Detour() {
  return (
    <div className="mx-auto mt-8 flex max-w-xl flex-col gap-4">
      <SearchField />
      <nav aria-label="Browse" className="flex flex-wrap justify-center gap-x-5 text-sm">
        <DetourLink href={routes.trades()}>All trades</DetourLink>
        <DetourLink href={routes.shops()}>All shops</DetourLink>
        <DetourLink href={routes.home()}>Home</DetourLink>
      </nav>
    </div>
  );
}

function DetourLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="flex h-11 items-center font-semibold text-link hover:underline">
      {children}
    </Link>
  );
}
