import { ChevronRight } from "lucide-react";

import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { TradeIcon } from "@/components/trade-icon";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import type { DirectoryGroup, DirectoryLink, DirectoryTrade } from "@/lib/trade-directory";
import { asPhrase } from "@/lib/trades";
import { cn } from "@/lib/utils";

import { TradeDisclosure } from "./trade-disclosure";

/**
 * Every trade as a directory entry: its name and size, and its categories as
 * links with their counts.
 *
 * On a phone it is the list the home page shows — a row per trade saying what
 * is inside — with each trade's links folded under a chevron. From `md` each
 * trade is a card and its links are always out. The major trades span the
 * full width and map every group with its categories in columns; the rest
 * share a grid, listing more categories the bigger they are, and the next
 * tier down (`wide`) takes two cells on wide screens with its links in two
 * columns. Size is the fact the layout shows: three trades hold most of the
 * catalogue.
 *
 * The hairlines between phone rows are the list's background showing through
 * a 1px gap, as in TradeList; from `md` the gap opens and each card draws its
 * own border.
 */
export function TradeDirectory({ trades }: { trades: DirectoryTrade[] }) {
  return (
    <ul
      className={cn(
        "grid grid-cols-1 gap-px overflow-hidden rounded-card border border-line bg-line",
        "md:grid-cols-2 md:gap-3 md:overflow-visible md:rounded-none md:border-0 md:bg-transparent",
        "lg:grid-cols-3 xl:grid-cols-4",
      )}
    >
      {trades.map((trade) => (
        <li
          key={trade.domain}
          data-trade={trade.domain}
          data-major={trade.major ? "true" : undefined}
          className={cn(
            "min-w-0 bg-surface md:rounded-card md:border md:border-line",
            trade.major && "md:col-span-full",
            trade.wide && "xl:col-span-2",
          )}
        >
          <TradeDisclosure label={trade.label} head={<TradeHead trade={trade} />}>
            {trade.major ? <GroupColumns trade={trade} /> : <CategoryList trade={trade} />}
          </TradeDisclosure>
        </li>
      ))}
    </ul>
  );
}

function TradeHead({ trade }: { trade: DirectoryTrade }) {
  const image = objectImage(trade.domain);
  const frame = trade.major ? "size-[52px] md:size-14" : "size-[52px] md:size-11";
  return (
    <Link
      href={routes.department(trade.domain)}
      className={cn(
        "group flex min-h-11 items-center gap-3 py-2.5 pl-3 text-ink hover:bg-ground",
        "md:rounded-t-card md:px-4 md:py-3 md:hover:bg-transparent",
      )}
    >
      {image ? (
        <PhotoFrame src={image} alt="" size={52} className={cn("rounded-md", frame)} />
      ) : (
        <span
          className={cn(
            "grid shrink-0 place-items-center rounded-md border border-line bg-photo-frame",
            frame,
          )}
        >
          <TradeIcon domain={trade.domain} className="size-6 text-ink-3" />
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline justify-between gap-2 md:justify-start md:gap-3">
          <h2
            className={cn(
              "font-sans text-base font-semibold md:font-display md:font-bold md:group-hover:text-link",
              trade.major && "md:text-xl",
            )}
          >
            {trade.label}
          </h2>
          <span className="text-[13px] text-ink-3 tabular">
            {formatCount(trade.count)}
            <span className="hidden md:inline"> products</span>
          </span>
        </span>
        {trade.inside.length > 0 && (
          <span className="text-[13px] leading-snug text-pretty text-ink-2 md:hidden">
            {asPhrase(trade.inside)}
          </span>
        )}
        <span className="hidden text-[13px] text-ink-3 tabular md:block">
          {trade.categoryCount} {trade.categoryCount === 1 ? "category" : "categories"}
          {trade.major && (
            <>
              {" "}
              in {trade.groups.length} groups · {Math.round(trade.share * 100)}% of all products
            </>
          )}
        </span>
      </span>
    </Link>
  );
}

/** A major trade: every group, each with its categories, in columns. */
function GroupColumns({ trade }: { trade: DirectoryTrade }) {
  return (
    <div className="border-t border-line px-3 pt-3 pb-1 md:px-4 md:pt-4">
      <div className="gap-8 sm:columns-2 lg:columns-3 xl:columns-4">
        {trade.groups.map((group) => (
          <Group key={group.ref} group={group} />
        ))}
      </div>
    </div>
  );
}

function Group({ group }: { group: DirectoryGroup }) {
  return (
    <section data-group={group.ref} className="mb-4 break-inside-avoid">
      <h3 className="font-sans">
        <EntryLink link={group} className="font-semibold text-ink" />
      </h3>
      {group.categories.length > 0 && (
        <ul>
          {group.categories.map((category) => (
            <li key={category.ref}>
              <EntryLink link={category} />
            </li>
          ))}
        </ul>
      )}
      {group.more > 0 && (
        <MoreLink href={group.href}>
          {group.more} more in {group.name}
        </MoreLink>
      )}
    </section>
  );
}

/** A minor trade: its biggest categories, then the way to the rest. */
function CategoryList({ trade }: { trade: DirectoryTrade }) {
  return (
    <div className="border-t border-line px-3 pt-2 pb-2 md:px-4 md:pb-3">
      <ul className={cn(trade.wide && "gap-8 xl:columns-2")}>
        {trade.categories.map((category) => (
          <li key={category.ref}>
            <EntryLink link={category} />
          </li>
        ))}
      </ul>
      {trade.more > 0 && (
        <MoreLink href={routes.department(trade.domain)}>
          All {trade.categoryCount} categories in {trade.label}
        </MoreLink>
      )}
    </div>
  );
}

/** A name and its count, set like an index: name left, count right. */
function EntryLink({ link, className }: { link: DirectoryLink; className?: string }) {
  return (
    <Link
      href={link.href}
      className={cn(
        "flex min-h-11 items-center justify-between gap-3 text-sm text-ink-2 hover:text-link",
        "md:min-h-0 md:py-1",
        className,
      )}
    >
      <span className="min-w-0">{link.name}</span>{" "}
      <span className="shrink-0 text-[13px] font-normal text-ink-3 tabular">
        {formatCount(link.count)}
      </span>
    </Link>
  );
}

function MoreLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="flex min-h-11 items-center gap-0.5 text-sm text-link hover:underline md:min-h-0 md:py-1"
    >
      {children}
      <ChevronRight aria-hidden="true" className="size-4" />
    </Link>
  );
}
