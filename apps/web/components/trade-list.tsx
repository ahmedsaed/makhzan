import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { TradeIcon } from "@/components/trade-icon";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { asPhrase, type TradeSummary } from "@/lib/trades";
import { cn } from "@/lib/utils";

/**
 * Trades as rows, each saying what is inside: an object, the trade, its count
 * and its biggest categories in words. Never a grid of equal tiles of names —
 * three trades hold most of the catalogue, and "Seals & Bearings" alone does
 * not say O-rings.
 *
 * One column on phones, two from `md`. The hairlines between rows are the
 * list's own background showing through a 1px gap, so they stay single in
 * both layouts.
 */
export function TradeList({ trades, className }: { trades: TradeSummary[]; className?: string }) {
  return (
    <ul
      className={cn(
        "grid gap-px overflow-hidden rounded-card border border-line bg-line md:grid-cols-2",
        className,
      )}
    >
      {trades.map((trade) => (
        <li
          key={trade.domain}
          data-trade={trade.domain}
          className="bg-surface md:last:odd:col-span-2"
        >
          <TradeRow trade={trade} />
        </li>
      ))}
    </ul>
  );
}

function TradeRow({ trade }: { trade: TradeSummary }) {
  const image = objectImage(trade.domain);
  return (
    <Link
      href={routes.trade(trade.domain)}
      className="flex min-h-11 items-center gap-3 px-3 py-2.5 text-ink hover:bg-ground"
    >
      {image ? (
        <PhotoFrame src={image} alt="" size={52} className="rounded-md" />
      ) : (
        <span className="grid size-[52px] shrink-0 place-items-center rounded-md border border-line bg-photo-frame">
          <TradeIcon domain={trade.domain} className="size-6 text-ink-3" />
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline justify-between gap-2">
          <span className="text-base font-semibold">{trade.label}</span>
          <span className="text-[13px] text-ink-3 tabular">{formatCount(trade.count)}</span>
        </span>
        {trade.inside.length > 0 && (
          <span className="truncate text-[13px] text-ink-2">{asPhrase(trade.inside)}</span>
        )}
      </span>
    </Link>
  );
}
