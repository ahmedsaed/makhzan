import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { PriceRange } from "@/components/price";
import { ShopsBadge } from "@/components/shops-badge";
import { titleOf, type SearchHit } from "@/lib/api";
import { freshnessTier, parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * One search result, as a list row or a grid card.
 *
 * Both are rendered from the same props and show the same facts — title, price
 * or range, the shop or "N shops", and freshness (rule C1) — so switching views
 * never hides something a visitor was relying on. Both link to the product page
 * and nowhere else (P1): the product page is where the freshness warning and
 * the other shops live, so skipping it to reach a shop would skip both.
 *
 * Not client components themselves, but safe to render inside one (ResultList
 * does): they read nothing but their props.
 */
export type ResultProps = {
  hit: SearchHit;
  /** The render's clock, so every row in a list agrees on "N days ago" and a
   *  hydrated list agrees with the server's. Defaults to now. */
  now?: Date;
  /** Above the fold: load the photo eagerly. */
  priority?: boolean;
  /** On a page already scoped to one shop (its own page), its name on every
   *  row says nothing: a one-shop result shows freshness alone. A product
   *  other shops sell too keeps its "N shops" badge, which is news there. */
  hideShop?: boolean;
};

/** The product's shop when there is one, the badge when there are several. */
function Shops({ hit, hideShop = false }: { hit: SearchHit; hideShop?: boolean }) {
  if (hit.supplier_count >= 2) return <ShopsBadge count={hit.supplier_count} />;
  if (hideShop) return null;
  return <span className="min-w-0 truncate text-ink-2">{hit.supplier_name ?? "1 shop"}</span>;
}

function displayTitle(hit: SearchHit): string {
  return titleOf(hit) || hit.part_number || "Untitled product";
}

/**
 * Phones: photo, two-line title, price, then shop · freshness. From `md` the
 * row becomes columns — photo · title and category · shop and freshness · price
 * — with the price end-aligned, because the column is the comparison.
 */
export function ResultRow({ hit, now, priority = false, hideShop = false }: ResultProps) {
  const title = displayTitle(hit);
  const verified = parseVerified(hit.last_verified_at);
  // A stale price's warning is longer than a phone's line: it goes under the
  // shop rather than beside it, so no separator is left dangling at a wrap.
  // Otherwise "checked 12 days ago" never wraps and the shop name truncates.
  const stacked = verified !== null && freshnessTier(verified, now) === "warn";
  // Nothing to put beside the freshness: no separator.
  const shopless = hideShop && hit.supplier_count < 2;
  return (
    <li data-result="row" className="border-b border-line">
      {/* Grid areas rather than two copies of the markup: each fact exists
          once in the DOM and only its position changes with the width. */}
      <Link
        href={routes.product(hit.id, titleOf(hit) || hit.part_number)}
        className="grid grid-cols-[72px_minmax(0,1fr)] grid-rows-[auto_auto_1fr] gap-x-3 gap-y-1 px-4 py-3 [grid-template-areas:'photo_title'_'photo_price'_'photo_meta'] hover:bg-ground md:grid-cols-[72px_minmax(0,1fr)_16rem_9rem] md:grid-rows-1 md:items-center md:gap-x-5 md:[grid-template-areas:'photo_title_meta_price']"
      >
        <PhotoFrame
          src={hit.image}
          shop={hit.image_shop?.name}
          alt={title}
          size={72}
          priority={priority}
          className="self-start [grid-area:photo]"
        />
        <span className="flex min-w-0 flex-col gap-0.5 [grid-area:title]">
          <span className="line-clamp-2 text-[15px] leading-snug font-medium text-ink">
            {title}
          </span>
          {hit.category_name && (
            <span className="hidden truncate text-[13px] text-ink-3 md:block">
              {hit.category_name}
            </span>
          )}
        </span>
        <PriceRange
          min={hit.min_price}
          max={hit.max_price}
          currency={hit.currency}
          className="text-base [grid-area:price] md:text-end"
        />
        <span
          data-meta={stacked ? "stacked" : "inline"}
          className={cn(
            "flex min-w-0 gap-x-1.5 gap-y-1 self-start text-[13px] [grid-area:meta] md:flex-col md:items-start md:self-center",
            stacked ? "flex-col items-start" : "items-center",
          )}
        >
          <Shops hit={hit} hideShop={hideShop} />
          {!stacked && !shopless && (
            <span aria-hidden="true" className="text-ink-3 md:hidden">
              ·
            </span>
          )}
          <Freshness
            lastVerified={verified}
            now={now}
            className={stacked ? undefined : "shrink-0 whitespace-nowrap"}
          />
        </span>
      </Link>
    </li>
  );
}

/** Grid: photo on top, three-line title, then the same facts as the row. */
export function ResultCard({ hit, now, priority = false, hideShop = false }: ResultProps) {
  const title = displayTitle(hit);
  return (
    <li
      data-result="card"
      className="overflow-hidden rounded-card border border-line bg-surface hover:border-line-strong"
    >
      <Link
        href={routes.product(hit.id, titleOf(hit) || hit.part_number)}
        className="flex h-full flex-col"
      >
        <PhotoFrame
          src={hit.image}
          shop={hit.image_shop?.name}
          alt={title}
          priority={priority}
          // The card is the frame; the photo sits flush at its top.
          className="rounded-none border-0 border-b"
        />
        <div className="flex flex-1 flex-col gap-1 p-2.5 text-xs">
          <span className="line-clamp-3 min-h-[3.9em] text-sm leading-[1.3] font-medium text-ink">
            {title}
          </span>
          <PriceRange
            min={hit.min_price}
            max={hit.max_price}
            currency={hit.currency}
            className="text-[15px]"
          />
          {!(hideShop && hit.supplier_count < 2) && (
            <span className="flex min-w-0 self-start">
              <Shops hit={hit} />
            </span>
          )}
          <Freshness lastVerified={parseVerified(hit.last_verified_at)} now={now} />
        </div>
      </Link>
    </li>
  );
}
