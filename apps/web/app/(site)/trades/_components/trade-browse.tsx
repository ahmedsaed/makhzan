import { ChevronLeft } from "lucide-react";

import { Breadcrumb, type Crumb } from "@/components/breadcrumb";
import { Link } from "@/components/link";
import { ObjectTile } from "@/components/object-tile";
import { NotAnswering, Results } from "@/components/results";
import { SearchField } from "@/components/search-field";
import { Container } from "@/components/section";
import { tradeIcon } from "@/components/trade-icon";
import { categoryNameOf, type Category } from "@/lib/api";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import {
  fetchResults,
  parseResultsQuery,
  type RawParams,
  type ResultsQuery,
} from "@/lib/results-query";
import { totalOf, tradeLabel, tradeTree, type TradeNode } from "@/lib/trades";

export type { RawParams };

/**
 * A trade, or one of its categories: the same page, narrowed. The header names
 * it and offers "Search in {trade}"; the groups are object tiles, the selected
 * group's categories smaller ones; and the results start straight away, so no
 * page here is a dead-end list of links.
 *
 * The results are the search page's (components/results.tsx), on the same URL
 * contract (lib/results-query.ts), with the trade — and on a category page the
 * category — fixed by the path. `?category=` may narrow further, but only to
 * something inside the page's own category; anything else is ignored rather
 * than allowed to show another trade's products under this one's name.
 *
 * `categories` is null when the taxonomy could not be fetched: the page then
 * says so instead of failing.
 */
export async function TradeBrowse({
  trade,
  categories,
  selected = null,
  params,
}: {
  trade: string;
  /** The trade's whole slice of the taxonomy, or null if it is unavailable. */
  categories: Category[] | null;
  /** The category the page is narrowed to; null on the trade's own page. */
  selected?: Category | null;
  params: RawParams;
}) {
  const label = tradeLabel(trade);
  if (!categories) {
    return (
      <>
        <TradeHeader trade={trade} heading={label} />
        <Container className="py-3.5">
          <NotAnswering title="The catalogue is not answering" />
        </Container>
      </>
    );
  }

  const tree = tradeTree(categories, selected?.ref ?? null);
  const pathname = selected ? routes.category(selected.ref) : routes.trade(trade);
  const query = scopedQuery(params, trade, categories, selected);
  const data = await fetchResults(query, { baseCategory: selected?.ref });

  const heading = selected ? categoryNameOf(selected) : label;
  // The taxonomy's count, in and out of stock; the toolbar counts what shows.
  const count = selected
    ? totalOf(selected.ref, categories)
    : categories.reduce((sum, category) => sum + category.count, 0);
  const crumbs: Crumb[] = [
    { label: "Trades", href: routes.trades() },
    { label, href: routes.trade(trade) },
  ];
  if (tree.group && tree.group.ref !== selected?.ref) {
    crumbs.push({ label: categoryNameOf(tree.group), href: routes.category(tree.group.ref) });
  }
  if (selected) crumbs.push({ label: categoryNameOf(selected) });

  const shelf = tree.group ? tree.children : tree.top;
  const shelfTitle = tree.group
    ? `${categoryNameOf(tree.group)} · ${formatCount(tree.group.total)}`
    : `Biggest in ${label}`;
  const tile = (node: TradeNode, size: "md" | "sm") => (
    <ObjectTile
      key={node.ref}
      href={routes.category(node.ref)}
      label={categoryNameOf(node)}
      image={objectImage(node.ref)}
      icon={tradeIcon(trade)}
      count={size === "sm" ? node.total : undefined}
      current={node.ref === (size === "md" ? tree.group?.ref : selected?.ref)}
      size={size}
    />
  );
  const names = new Map(categories.map((c) => [c.ref, categoryNameOf(c)]));

  return (
    <>
      <TradeHeader
        trade={trade}
        heading={heading}
        count={count}
        crumbs={selected ? crumbs : undefined}
      >
        {tree.groups.length > 1 && (
          // As many columns as fit at 76px, so a long group name ("Bearings &
          // Transmission") wraps between words rather than inside one.
          <nav
            aria-label="Groups"
            className="grid grid-cols-[repeat(auto-fill,minmax(4.75rem,1fr))] gap-1.5 sm:grid-cols-6 lg:grid-cols-8"
          >
            {tree.groups.map((group) => tile(group, "md"))}
          </nav>
        )}
      </TradeHeader>

      <Container className="py-3.5">
        {shelf.length > 0 && (
          <section aria-labelledby="shelf-heading" className="mb-4 flex flex-col gap-2">
            <h2 id="shelf-heading" className="font-sans text-[13px] font-semibold text-ink-2">
              {shelfTitle}
            </h2>
            <nav
              aria-label="Categories"
              className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10"
            >
              {shelf.map((node) => tile(node, "sm"))}
            </nav>
          </section>
        )}

        {data.result ? (
          <Results
            pathname={pathname}
            raw={params}
            query={query}
            data={{ ...data, result: data.result }}
            names={names}
            locked={
              selected && query.category === selected.ref ? ["domain", "category"] : ["domain"]
            }
          />
        ) : (
          <NotAnswering />
        )}
      </Container>
    </>
  );
}

/**
 * The search page's query, with the trade fixed and the category held inside
 * the page's own. A `?category=` from another trade, or from outside this
 * category, is dropped; so are `domain` and `shop`, which the page decides.
 */
function scopedQuery(
  params: RawParams,
  trade: string,
  categories: Category[],
  selected: Category | null,
): ResultsQuery {
  const query = parseResultsQuery(params);
  const parents = new Map(categories.map((c) => [c.ref, c.parent]));
  const within = (ref: string, ancestor: string) => {
    for (let at: string | null | undefined = ref; at; at = parents.get(at)) {
      if (at === ancestor) return true;
    }
    return false;
  };
  const asked = query.category;
  const category =
    asked && parents.has(asked) && (!selected || within(asked, selected.ref))
      ? asked
      : selected?.ref;
  return { ...query, domain: trade, shop: undefined, category };
}

/** Back link or breadcrumb, the name, its count, and "Search in {trade}". */
function TradeHeader({
  trade,
  heading,
  count,
  crumbs,
  children,
}: {
  trade: string;
  heading: string;
  count?: number;
  crumbs?: Crumb[];
  children?: React.ReactNode;
}) {
  const label = tradeLabel(trade);
  return (
    <header className="border-b border-line bg-surface">
      <Container className="flex flex-col gap-2.5 pt-1 pb-3.5">
        {crumbs ? (
          <Breadcrumb items={crumbs} className="flex min-h-11 items-center" />
        ) : (
          <Link
            href={routes.trades()}
            className="inline-flex h-11 items-center gap-1 self-start text-sm text-ink-2 hover:text-ink"
          >
            <ChevronLeft aria-hidden="true" className="size-4" />
            All trades
          </Link>
        )}
        <div className="flex items-baseline justify-between gap-3">
          <h1 className="text-[26px] leading-tight">{heading}</h1>
          {count !== undefined && (
            <span data-catalogue-count className="shrink-0 text-[13px] text-ink-3 tabular">
              {formatCount(count)} products
            </span>
          )}
        </div>
        <SearchField
          compact
          label={`Search in ${label}`}
          placeholder={`Search in ${label}`}
          scope={{ domain: trade }}
          className="md:max-w-xl"
        />
        {children}
      </Container>
    </header>
  );
}
