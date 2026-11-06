import { ArrowRight } from "lucide-react";

import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { ResultCard } from "@/components/result";
import { TradeIcon } from "@/components/trade-icon";
import { TradeList } from "@/components/trade-list";
import type { SearchHit, ShopSummary } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { EXAMPLE_SEARCHES, exampleHref, type TradeCard } from "@/lib/home";
import { routes } from "@/lib/routes";
import { isStale, tradesInWords } from "@/lib/shops";
import type { TradeSummary } from "@/lib/trades";
import { cn } from "@/lib/utils";

/**
 * The home page's sections. Each takes data the page has already fetched and
 * renders nothing of its own accord: whether a section appears at all is the
 * page's decision, made on whether its fetch succeeded.
 *
 * Every block fills the page container on desktop; only paragraphs keep a
 * reading measure.
 */

/** Section heading with an optional line under it and a link at its end. */
function SectionHead({
  id,
  title,
  lead,
  more,
}: {
  id: string;
  title: string;
  lead?: React.ReactNode;
  more?: { href: string; label: string };
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
      <div className="flex max-w-[62ch] flex-col gap-1">
        <h2 id={id} className="text-xl text-ink sm:text-2xl">
          {title}
        </h2>
        {lead && <p className="text-[15px] leading-relaxed text-ink-2">{lead}</p>}
      </div>
      {more && (
        <Link
          href={more.href}
          className="flex min-h-11 items-center gap-1 text-[15px] font-medium text-link hover:underline"
        >
          {more.label}
          <ArrowRight aria-hidden="true" className="size-4" />
        </Link>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //

/** "Try:" and a row of searches that are known to return a page of results. */
export function ExampleSearches({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <p className="text-[13px] font-medium text-ink-3">Try a search</p>
      {/* One scrolling row on phones, where wrapped chips would push the
          trades a screen down; wrapped from `sm`. */}
      <ul
        aria-label="Example searches"
        className="-mx-4 flex [scrollbar-width:none] gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0"
      >
        {EXAMPLE_SEARCHES.map((query) => (
          <li key={query}>
            <Link
              href={exampleHref(query)}
              className="flex h-11 items-center rounded-full border border-line-strong bg-surface px-3.5 text-sm whitespace-nowrap text-ink hover:border-ink-3 sm:h-9"
            >
              {query}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------- //

const STEPS = [
  {
    title: "Search",
    text: "One search across every listed shop's public catalogue, by part number or by name.",
  },
  {
    title: "Compare",
    text: "Each result shows its price, its shop or how many shops sell it, and when it was last checked.",
  },
  {
    title: "Buy from the shop",
    text: "makhzan sells nothing. Every offer links to the shop's own page, where you buy.",
  },
] as const;

/** Three steps, so nobody arrives expecting a cart. */
export function HowItWorks({ className }: { className?: string }) {
  return (
    <section
      aria-labelledby="how-heading"
      data-home-section="how"
      className={cn("rounded-card border border-line bg-surface p-5", className)}
    >
      <h2 id="how-heading" className="text-lg text-ink">
        How makhzan works
      </h2>
      <ol className="mt-3 grid gap-4 sm:grid-cols-3 lg:grid-cols-1">
        {STEPS.map((step, index) => (
          <li key={step.title} className="flex gap-3">
            <span
              aria-hidden="true"
              className="grid size-7 shrink-0 place-items-center rounded-full border border-line-strong font-display text-sm font-bold text-ink tabular"
            >
              {index + 1}
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-[15px] font-semibold text-ink">{step.title}</span>
              <span className="text-sm leading-snug text-ink-2">{step.text}</span>
            </span>
          </li>
        ))}
      </ol>
      <Link
        href={routes.howWeCrawl()}
        className="mt-3 flex min-h-11 items-center text-sm font-medium text-link hover:underline"
      >
        How prices are collected
      </Link>
    </section>
  );
}

// --------------------------------------------------------------------------- //

/** Trades shown in full on the home page; the rest are named underneath. */
const HOME_TRADES = 8;

/**
 * Phones keep the compact trade rows (one column, names of what is inside);
 * from `md` each trade is a card whose biggest categories are links, four
 * across on a desktop, so the catalogue's shape fills the page.
 */
export function HomeTrades({ cards, rows }: { cards: TradeCard[]; rows: TradeSummary[] }) {
  const shown = cards.slice(0, HOME_TRADES);
  const rest = cards.slice(HOME_TRADES);
  return (
    <section aria-labelledby="trades-heading" data-home-section="trades">
      <SectionHead
        id="trades-heading"
        title="Browse by trade"
        more={{ href: routes.trades(), label: `All ${cards.length} trades` }}
      />

      <TradeList trades={rows.slice(0, HOME_TRADES)} className="md:hidden" />

      <ul className="hidden gap-3 md:grid md:grid-cols-2 lg:grid-cols-4">
        {shown.map((card) => (
          <li
            key={card.domain}
            data-home-trade={card.domain}
            className="flex flex-col rounded-card border border-line bg-surface"
          >
            <Link
              href={routes.trade(card.domain)}
              className="flex items-center gap-3 rounded-t-card border-b border-line px-4 py-3 text-ink hover:bg-ground"
            >
              <span className="grid size-10 shrink-0 place-items-center rounded-md border border-line bg-photo-frame">
                <TradeIcon domain={card.domain} className="size-5 text-ink-3" />
              </span>
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-base font-semibold">{card.label}</span>
                <span className="text-[13px] text-ink-3 tabular">
                  {formatCount(card.count)} products
                </span>
              </span>
            </Link>
            {card.categories.length > 0 && (
              <ul className="flex flex-col py-1.5">
                {card.categories.map((category) => (
                  <li key={category.ref}>
                    <Link
                      href={routes.category(category.ref)}
                      className="flex items-baseline justify-between gap-3 px-4 py-1.5 text-sm text-ink-2 hover:bg-ground hover:text-ink"
                    >
                      <span className="truncate">{category.name}</span>
                      <span className="shrink-0 text-[13px] text-ink-3 tabular">
                        {formatCount(category.count)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      {rest.length > 0 && (
        <p className="mt-4 hidden text-sm leading-relaxed text-ink-2 md:block">
          <span className="font-medium text-ink">Also: </span>
          {rest.map((card, index) => (
            <span key={card.domain}>
              {index > 0 && ", "}
              <Link href={routes.trade(card.domain)} className="text-link hover:underline">
                {card.label}
              </Link>{" "}
              <span className="text-ink-3 tabular">{formatCount(card.count)}</span>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //

/**
 * Products more than one shop sells, with the spread of their prices: the
 * comparison makhzan exists for, shown before anyone has to search for it.
 * Rare (about 1.4% of products), which is why it is a strip and not a page.
 */
export function SeveralShops({
  hits,
  total,
  now,
}: {
  hits: SearchHit[];
  total: number | null;
  now: Date;
}) {
  return (
    <section aria-labelledby="several-heading" data-home-section="several-shops">
      <SectionHead
        id="several-heading"
        title="Sold by several shops"
        lead={
          <>
            {total !== null && (
              <>
                <span className="font-semibold text-ink tabular">{formatCount(total)}</span>{" "}
                products in stock are sold by two or more shops.{" "}
              </>
            )}
            Prices for the same part can differ a lot between shops. Tick{" "}
            <span className="font-medium text-ink">2+ shops</span> on any search to see only these.
          </>
        }
      />
      {/* Four on phones (two rows), six from `sm`. */}
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 max-sm:[&>li:nth-child(n+5)]:hidden">
        {hits.map((hit) => (
          <ResultCard key={hit.id} hit={hit} now={now} />
        ))}
      </ul>
    </section>
  );
}

// --------------------------------------------------------------------------- //

/** Every listed shop: what it carries, how much, and how fresh it is (F1, F2). */
export function HomeShops({ shops, now }: { shops: ShopSummary[]; now: Date }) {
  return (
    <section aria-labelledby="shops-heading" data-home-section="shops">
      <SectionHead
        id="shops-heading"
        title="The shops"
        lead={`makhzan reads the public catalogues of ${shops.length} ${
          shops.length === 1 ? "shop" : "shops"
        } and rechecks each about weekly.`}
        more={{ href: routes.shops(), label: "All shops" }}
      />
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {shops.map((shop) => (
          <li
            key={shop.slug}
            data-home-shop={shop.slug}
            data-stale={isStale(shop.last_verified_at, now) || undefined}
          >
            <Link
              href={routes.shop(shop.slug)}
              className="flex h-full flex-col gap-1 rounded-card border border-line bg-surface px-4 py-3 hover:border-line-strong"
            >
              <span className="text-base font-semibold text-ink">{shop.name}</span>
              {shop.domains.length > 0 && (
                <span className="hidden text-[13px] text-ink-2 sm:block">
                  {tradesInWords(shop.domains, 2)}
                </span>
              )}
              <span className="mt-auto pt-1 text-sm text-ink-2 tabular">
                <span className="font-semibold text-ink">{formatCount(shop.listing_count)}</span>{" "}
                {shop.listing_count === 1 ? "product" : "products"} ·{" "}
                {formatCount(shop.in_stock_count)} in stock
              </span>
              <Freshness
                lastVerified={parseVerified(shop.last_verified_at)}
                now={now}
                className="self-start text-[13px]"
              />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --------------------------------------------------------------------------- //

/** For the shop owners who land here: they can add, correct or leave. */
export function ForShops({ className }: { className?: string }) {
  return (
    <section
      aria-labelledby="for-shops-heading"
      data-home-section="for-suppliers"
      className={cn(
        "flex flex-col gap-3 rounded-card border border-line bg-surface p-5 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <div className="flex max-w-[70ch] flex-col gap-1">
        <h2 id="for-shops-heading" className="text-lg text-ink">
          Own a shop?
        </h2>
        <p className="text-[15px] leading-relaxed text-ink-2">
          Listing is free and no shop pays to appear. Ask to add your shop, correct its details, or
          remove it.
        </p>
      </div>
      <Link
        href={routes.forSuppliers()}
        className="flex h-11 shrink-0 items-center justify-center self-start rounded-control border-[1.5px] border-line-strong px-4 text-[15px] font-semibold text-ink hover:border-ink-3 sm:self-auto"
      >
        For suppliers
      </Link>
    </section>
  );
}

// --------------------------------------------------------------------------- //

/**
 * The totals as figures, for the desktop hero: products, shops, trades and
 * categories, every one counted by the API. Phones keep the one-line version.
 */
export function HomeStats({
  stats,
  trades,
  className,
}: {
  stats: { products: number; suppliers: number; categories: number } | null;
  trades: number;
  className?: string;
}) {
  const figures = [
    stats && { label: "products", value: stats.products },
    stats && { label: "shops", value: stats.suppliers },
    trades > 0 && { label: "trades", value: trades },
    stats && { label: "categories", value: stats.categories },
  ].filter((figure): figure is { label: string; value: number } => Boolean(figure));
  if (figures.length === 0) return null;
  return (
    <dl
      className={cn(
        "grid auto-cols-fr grid-flow-col divide-x divide-line rounded-card border border-line bg-surface",
        className,
      )}
    >
      {figures.map((figure) => (
        <div key={figure.label} className="flex flex-col-reverse gap-0.5 px-4 py-3">
          <dt className="text-[13px] text-ink-2">{figure.label}</dt>
          <dd className="figure text-2xl text-ink">{formatCount(figure.value)}</dd>
        </div>
      ))}
    </dl>
  );
}
