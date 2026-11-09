import { Chip, ChipBar } from "@/components/chips";
import { FilterRail, FilterSheet } from "@/components/filter-panel";
import { Link } from "@/components/link";
import { ResultList, ViewToggle } from "@/components/result-list";
import { ResultsFilters } from "@/components/results-filters";
import { SortSelect } from "@/components/sort-select";
import type { SearchResponse } from "@/lib/api";
import { formatCount, formatPriceRange, plural } from "@/lib/format";
import {
  PAGE_SIZE,
  SORTS,
  countText,
  flatParams,
  groupCategoryFacet,
  hiddenCounts,
  resultsLinks,
  type HiddenCounts,
  type RawParams,
  type ResultsData,
  type ResultsQuery,
} from "@/lib/results-query";
import { departmentLabel } from "@/lib/departments";
import { STALE_AFTER_DAYS } from "@/lib/freshness";
import { cn } from "@/lib/utils";

type Links = ReturnType<typeof resultsLinks>;

/** Parameters a page fixes itself (a department page's department), which the visitor
 *  therefore cannot remove from the results. */
export type Locked = ("domain" | "category" | "shop")[];

/**
 * The results half of every results page — search, department, category, a shop's
 * search: the chip bar, the "Category, price" sheet (a rail on desktop), the
 * toolbar, the results or why there are none, and paging. One component, so
 * the pages cannot drift apart in wording or layout.
 *
 * `top` is an optional block above the results (search's "Top categories");
 * from `lg` it spans the page above the rail.
 */
export function Results({
  pathname,
  raw,
  query,
  data,
  names,
  locked = [],
  shopName,
  hideShop,
  top,
  className,
}: {
  pathname: string;
  raw: RawParams;
  query: ResultsQuery;
  data: ResultsData & { result: SearchResponse };
  /** `ref` → display name, from GET /categories. */
  names: Map<string, string>;
  locked?: Locked;
  shopName?: string;
  /** One shop's own page: results leave its name out (see ResultRow). */
  hideShop?: boolean;
  top?: React.ReactNode;
  className?: string;
}) {
  const { result } = data;
  const links = resultsLinks(pathname, raw, query);
  const total = result.total ?? 0;
  const hidden = hiddenCounts(query, data);
  const now = new Date();
  const removable = (key: Locked[number]) => !locked.includes(key);

  // The category list, counted as if each were picked.
  const wide = data.wide ?? result;
  const groups = groupCategoryFacet(wide.facets?.category_ref);
  const picked = removable("category") ? query.category : undefined;
  if (picked && !groups.some((g) => g.categories.some((c) => c.ref === picked))) {
    // The picked category must stay visible (and checked) even at zero, and a
    // group (whose products sit on its children) is never in the leaf facet.
    groups.push({
      domain: picked.split(":")[0],
      count: 0,
      categories: [{ ref: picked, count: 0 }],
    });
  }
  const filters = (variant: "sheet" | "rail") => (
    <ResultsFilters
      pathname={pathname}
      raw={raw}
      query={{ ...query, category: picked }}
      groups={groups}
      names={names}
      anyCount={wide.total ?? total}
      variant={variant}
    />
  );

  // Narrowings beyond the two everyday chips, each removable from the bar so
  // the result count is never unexplained.
  const active: { label: string; href: string }[] = [];
  if (query.domain && removable("domain")) {
    active.push({ label: departmentLabel(query.domain), href: links.clear("domain") });
  }
  if (picked) {
    active.push({ label: names.get(picked) ?? picked, href: links.clear("category") });
  }
  if (query.minPrice !== undefined || query.maxPrice !== undefined) {
    active.push({ label: priceLabel(query), href: links.clear("min_price", "max_price") });
  }
  const sheetCount = [picked, query.minPrice ?? query.maxPrice].filter(
    (v) => v !== undefined,
  ).length;

  return (
    // One grid, two orders: on a phone chips → top → results; from `lg` the
    // top block spans the page and the rail runs down the left beside the
    // chips and results.
    <div
      className={cn(
        "flex flex-col gap-3 lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:grid-rows-[auto_auto_1fr] lg:gap-x-8 lg:gap-y-4",
        className,
      )}
    >
      <ChipBar className="lg:col-start-2 lg:row-start-2">
        <Chip href={links.inStock} active={query.inStockOnly}>
          In stock
        </Chip>
        <Chip href={links.fresh} active={query.freshOnly}>
          Recently checked
        </Chip>
        <Chip href={links.twoShops} active={Boolean(query.minSuppliers)}>
          2+ shops
        </Chip>
        <FilterSheet activeCount={sheetCount}>{filters("sheet")}</FilterSheet>
        {active.map((chip) => (
          <Chip key={chip.href} href={chip.href} active>
            {chip.label} ✕
          </Chip>
        ))}
      </ChipBar>

      {top && <div className="lg:col-span-2 lg:row-start-1">{top}</div>}

      <FilterRail className="lg:col-start-1 lg:row-span-2 lg:row-start-2">
        {filters("rail")}
      </FilterRail>

      <div className="min-w-0 lg:col-start-2 lg:row-start-3">
        <ResultsToolbar
          pathname={pathname}
          raw={raw}
          query={query}
          total={total}
          hidden={hidden}
          links={links}
        />

        {total === 0 ? (
          <NoResults
            query={query}
            links={links}
            hidden={hidden}
            shopName={shopName}
            removable={removable}
          />
        ) : (
          <>
            <ResultList
              hits={result.hits}
              now={now}
              hideShop={hideShop}
              className="-mx-4 mt-3 md:mx-0 lg:data-[view=list]:overflow-hidden lg:data-[view=list]:rounded-card lg:data-[view=list]:border-x"
            />
            <Pagination offset={query.offset} total={total} links={links} />
          </>
        )}
      </div>
    </div>
  );
}

/**
 * The count, "N more out of stock" (one click shows them, rule C2), "N more
 * out of date" (likewise, C2b), the sort and the list/grid toggle. Each count
 * is exactly what its own click adds; results both out of stock and out of
 * date are in neither (see `hiddenCounts`). A phone has no room for all of it on one line:
 * the count gets its own, sort and the view toggle share the next.
 */
export function ResultsToolbar({
  pathname,
  raw,
  query,
  total,
  hidden,
  links,
}: {
  pathname: string;
  raw: RawParams;
  query: ResultsQuery;
  total: number;
  hidden: HiddenCounts;
  links: Links;
}) {
  const more = [
    { count: hidden.outOfStock, href: links.showOutOfStock, label: "out of stock", key: "stock" },
    { count: hidden.stale, href: links.showStale, label: "out of date", key: "stale" },
  ].filter((item) => item.count > 0);
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 sm:gap-y-2">
      <p
        data-count
        className="basis-full text-[13px] text-ink-2 sm:me-auto sm:basis-auto lg:text-sm"
      >
        <span className="tabular">{countText(total, query.inStockOnly)}</span>
        {more.map((item) => (
          <span key={item.key}>
            {" · "}
            <Link
              href={item.href}
              data-show-hidden={item.key}
              title={
                item.key === "stale"
                  ? `Not checked in the last ${STALE_AFTER_DAYS} days: prices may be out of date`
                  : undefined
              }
              // 44px to tap on a phone (S4); the toolbar's own height from `sm`.
              className="inline-flex min-h-11 items-center text-link underline-offset-2 hover:underline sm:min-h-0"
            >
              {formatCount(item.count)} more {item.label}
            </Link>
          </span>
        ))}
      </p>
      {total > 0 && (
        <>
          <SortSelect
            pathname={pathname}
            params={flatParams(raw)}
            options={SORTS}
            current={query.sort ?? ""}
            className="me-auto sm:me-0"
          />
          <ViewToggle />
        </>
      )}
    </div>
  );
}

/** Previous · "25–48 of 120" · Next, as links: every page is a URL. */
export function Pagination({
  offset,
  total,
  links,
}: {
  offset: number;
  total: number;
  links: Links;
}) {
  if (total <= PAGE_SIZE && offset === 0) return null;
  const button =
    "flex h-11 items-center rounded-control border border-line-strong bg-surface px-4 text-ink hover:border-ink-3";
  return (
    <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-3 text-sm">
      {offset > 0 ? (
        <Link href={links.page(Math.max(0, offset - PAGE_SIZE))} rel="prev" className={button}>
          Previous
        </Link>
      ) : (
        <span />
      )}
      {offset < total && (
        <span className="text-[13px] text-ink-3 tabular">
          {formatCount(offset + 1)}–{formatCount(Math.min(offset + PAGE_SIZE, total))} of{" "}
          {formatCount(total)}
        </span>
      )}
      {offset + PAGE_SIZE < total ? (
        <Link href={links.page(offset + PAGE_SIZE)} rel="next" className={button}>
          Next
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}

/** The API could not be reached: the page stays up and says so. */
export function NotAnswering({
  title = "Search is not answering",
  className,
}: {
  title?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      data-state="not-answering"
      className={cn("rounded-card border border-line bg-surface px-5 py-8", className)}
    >
      <p className="font-display text-base font-bold text-ink">{title}</p>
      <p className="mt-1 text-sm text-ink-2">
        The catalogue could not be reached just now. Try again in a minute.
      </p>
    </div>
  );
}

function NoResults({
  query,
  links,
  hidden,
  shopName,
  removable,
}: {
  query: ResultsQuery;
  links: Links;
  hidden: HiddenCounts;
  shopName?: string;
  removable: (key: Locked[number]) => boolean;
}) {
  // Everything that matched is hidden by a default: say which, one click
  // shows them.
  const { outOfStock, stale, both } = hidden;
  if (outOfStock + stale + both > 0) {
    const button =
      "inline-flex h-11 items-center rounded-control px-4 text-sm font-semibold";
    const matched = outOfStock + stale + both;
    const state =
      stale + both === 0 ? "only-out-of-stock" : outOfStock + both === 0 ? "only-stale" : "only-hidden";
    return (
      <div data-state={state} className="mt-4 rounded-card border border-line bg-surface px-5 py-8">
        <p className="font-display text-base font-bold text-ink">
          {state === "only-out-of-stock"
            ? "Nothing in stock"
            : state === "only-stale"
              ? "Nothing checked recently"
              : "Nothing in stock and recently checked"}
        </p>
        <p className="mt-1 text-sm text-ink-2">
          {plural(matched, "product")} {matched === 1 ? "matches" : "match"},{" "}
          {state === "only-out-of-stock"
            ? `but no shop has ${matched === 1 ? "it" : "them"} in stock.`
            : state === "only-stale"
              ? `but none was checked in the last ${STALE_AFTER_DAYS} days, so prices may be out of date.`
              : `but each is out of stock, or not checked in the last ${STALE_AFTER_DAYS} days.`}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          {outOfStock > 0 && (
            <Link
              href={links.showOutOfStock}
              className={cn(button, "bg-action text-action-ink")}
            >
              Show {formatCount(outOfStock)} out of stock
            </Link>
          )}
          {stale > 0 && (
            <Link
              href={links.showStale}
              className={cn(
                button,
                outOfStock > 0
                  ? "border border-line-strong bg-surface text-ink hover:border-ink-3"
                  : "bg-action text-action-ink",
              )}
            >
              Show {formatCount(stale)} out of date
            </Link>
          )}
          {/* Only out of stock *and* out of date: neither link alone shows
              these, so the way to them is both at once. */}
          {both > 0 && (
            <Link
              href={links.showEverything}
              className={cn(
                button,
                outOfStock + stale > 0
                  ? "border border-line-strong bg-surface text-ink hover:border-ink-3"
                  : "bg-action text-action-ink",
              )}
            >
              Show all {formatCount(matched)}
            </Link>
          )}
        </div>
      </div>
    );
  }

  const removals: { label: string; href: string }[] = [];
  if (query.shop && removable("shop")) {
    removals.push({
      label: `Search all shops, not just ${shopName ?? query.shop}`,
      href: links.clear("shop"),
    });
  }
  if (query.minSuppliers) {
    removals.push({ label: "Remove “2+ shops”", href: links.clear("min_suppliers") });
  }
  if (query.category && removable("category")) {
    removals.push({ label: "Any category", href: links.clear("category") });
  }
  if (query.domain && removable("domain")) {
    removals.push({ label: "Every department", href: links.clear("domain") });
  }
  if (query.minPrice !== undefined || query.maxPrice !== undefined) {
    removals.push({ label: "Any price", href: links.clear("min_price", "max_price") });
  }

  return (
    <div
      data-state="no-results"
      className="mt-4 rounded-card border border-dashed border-line-strong px-5 py-10 text-center"
    >
      <p className="font-display text-base font-bold text-ink">Nothing matched</p>
      <p className="mt-1 text-sm text-ink-2">
        {removals.length > 0
          ? "Try without some of the filters."
          : query.q
            ? "Try the part number on its own, or fewer words."
            : "No products are filed here right now."}
      </p>
      {removals.length > 0 && (
        <ul className="mt-4 flex flex-wrap justify-center gap-2">
          {removals.map((removal) => (
            <li key={removal.href}>
              <Link
                href={removal.href}
                className="inline-flex h-11 items-center rounded-control border border-line-strong bg-surface px-4 text-sm text-ink hover:border-ink-3"
              >
                {removal.label}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** "EGP 100 – 500", "EGP 100 and up", "Up to EGP 500". */
function priceLabel({ minPrice, maxPrice }: ResultsQuery): string {
  if (minPrice !== undefined && maxPrice !== undefined) return formatPriceRange(minPrice, maxPrice);
  if (minPrice !== undefined) return `${formatPriceRange(minPrice)} and up`;
  return `Up to ${formatPriceRange(maxPrice)}`;
}
