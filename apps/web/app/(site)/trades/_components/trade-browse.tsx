import { ChevronLeft } from "lucide-react";

import { Breadcrumb, type Crumb } from "@/components/breadcrumb";
import { Chip, ChipBar } from "@/components/chips";
import { Link } from "@/components/link";
import { ObjectTile } from "@/components/object-tile";
import { ResultList, ViewToggle } from "@/components/result-list";
import { SearchField } from "@/components/search-field";
import { Container, Empty } from "@/components/section";
import { SortMenu } from "@/components/sort-menu";
import { tradeIcon } from "@/components/trade-icon";
import { categoryNameOf, searchProducts, type Category } from "@/lib/api";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { routes, withParams } from "@/lib/routes";
import { totalOf, tradeLabel, tradeTree, type TradeNode } from "@/lib/trades";

const PAGE_SIZE = 24;

export type RawParams = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * A trade, or one of its categories: the same page, narrowed. The header names
 * it and offers "Search in {trade}"; the groups are object tiles, the selected
 * group's categories smaller ones; and the results start straight away, so no
 * page here is a dead-end list of links.
 *
 * The URL is the only state, with the search page's parameters: `in_stock`
 * (on unless `false` — out of stock is hidden by default, rule C2),
 * `min_suppliers`, `sort` and `offset`.
 */
export async function TradeBrowse({
  trade,
  categories,
  selected = null,
  params,
}: {
  trade: string;
  /** The trade's whole slice of the taxonomy. */
  categories: Category[];
  /** The category the page is narrowed to; null on the trade's own page. */
  selected?: Category | null;
  params: RawParams;
}) {
  const label = tradeLabel(trade);
  const tree = tradeTree(categories, selected?.ref ?? null);
  const pathname = selected ? routes.category(selected.ref) : routes.trade(trade);

  // Search filters on one exact category, so a group — whose products are
  // filed on its children — cannot narrow the results; it shows the trade's.
  const isGroup = selected ? categories.some((c) => c.parent === selected.ref) : false;
  const offsetRaw = Number.parseInt(one(params.offset) ?? "", 10);
  const query = {
    domain: trade,
    category: selected && !isGroup ? selected.ref : undefined,
    inStock: one(params.in_stock) !== "false",
    minSuppliers: one(params.min_suppliers) ? 2 : undefined,
    sort: one(params.sort) || undefined,
    offset: Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : 0,
  };

  // The second query only counts what "In stock" is hiding, so the page can
  // say how many (C2). Skipped when nothing is being hidden.
  const [result, everything] = await Promise.all([
    searchProducts({ ...query, limit: PAGE_SIZE }),
    query.inStock ? searchProducts({ ...query, inStock: false, offset: 0, limit: 1 }) : null,
  ]);
  const total = result.total ?? 0;
  const hidden =
    everything?.total != null && result.total != null ? Math.max(0, everything.total - total) : 0;
  const showAll = withParams(pathname, params, { in_stock: "false" });

  const heading = selected ? categoryNameOf(selected) : label;
  const count = selected
    ? totalOf(selected.ref, categories)
    : categories.reduce((sum, category) => sum + category.count, 0);
  const crumbs: Crumb[] = [
    { label: "Trades", href: routes.trades() },
    { label, href: routes.trade(trade) },
  ];
  if (tree.group && tree.group.ref !== selected?.ref) {
    crumbs.push({
      label: categoryNameOf(tree.group),
      href: routes.category(tree.group.ref),
    });
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

  return (
    <>
      <header className="border-b border-line bg-surface">
        <Container className="flex flex-col gap-2.5 pt-1 pb-3.5">
          {selected ? (
            <Breadcrumb items={crumbs} className="flex min-h-10 items-center" />
          ) : (
            <Link
              href={routes.trades()}
              className="inline-flex h-10 items-center gap-1 self-start text-sm text-ink-2 hover:text-ink"
            >
              <ChevronLeft aria-hidden="true" className="size-4" />
              All trades
            </Link>
          )}
          <div className="flex items-baseline justify-between gap-3">
            <h1 className="text-[26px] leading-tight">{heading}</h1>
            <span className="shrink-0 text-[13px] text-ink-3 tabular">
              {formatCount(count)} products
            </span>
          </div>
          <SearchField
            compact
            label={`Search in ${label}`}
            placeholder={`Search in ${label}`}
            scope={{ domain: trade }}
            className="md:max-w-xl"
          />
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
        </Container>
      </header>

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

        {isGroup && (
          <p className="mb-3 text-[13px] text-ink-2">
            Showing everything in {label}. Pick a category above to narrow it.
          </p>
        )}

        <ChipBar>
          <Chip
            href={withParams(pathname, params, {
              in_stock: query.inStock ? "false" : null,
            })}
            active={query.inStock}
          >
            In stock
          </Chip>
          <Chip
            href={withParams(pathname, params, {
              min_suppliers: query.minSuppliers ? null : "2",
            })}
            active={Boolean(query.minSuppliers)}
          >
            2+ shops
          </Chip>
        </ChipBar>

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="text-[13px] text-ink-2">
            <strong className="text-ink tabular">{formatCount(total)}</strong> results
          </p>
          {hidden > 0 && (
            <Link
              href={showAll}
              className="flex min-h-11 items-center text-[13px] text-link hover:underline sm:min-h-0"
            >
              {formatCount(hidden)} more out of stock
            </Link>
          )}
          {/* Sort and view wrap together, so neither is stranded on a line. */}
          <div className="ms-auto flex items-center gap-2">
            <SortMenu pathname={pathname} params={params} current={query.sort ?? ""} />
            <ViewToggle />
          </div>
        </div>

        {result.hits.length === 0 ? (
          <div className="mt-4">
            <Empty
              title={hidden > 0 ? "Nothing in stock here" : "Nothing here yet"}
              hint={
                hidden > 0
                  ? "Everything here is out of stock right now."
                  : "No products are filed here right now."
              }
            />
          </div>
        ) : (
          <ResultList hits={result.hits} now={new Date()} className="-mx-4 mt-3 md:mx-0" />
        )}

        <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-3 text-sm">
          {query.offset > 0 ? (
            <Link
              href={withParams(pathname, params, {
                offset: query.offset - PAGE_SIZE > 0 ? String(query.offset - PAGE_SIZE) : null,
              })}
              className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
            >
              Previous
            </Link>
          ) : (
            <span />
          )}
          {query.offset + PAGE_SIZE < total && (
            <Link
              href={withParams(pathname, params, {
                offset: String(query.offset + PAGE_SIZE),
              })}
              className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
            >
              Next
            </Link>
          )}
        </nav>
      </Container>
    </>
  );
}
