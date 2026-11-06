import type { StockSignal } from "@/lib/api";
import { getDictionary, type Lang } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/**
 * Availability is a hint, never a stock count — suppliers publish a state, not a
 * number. "Unknown" is rendered rather than hidden: a shop that says nothing is
 * different from one that says out of stock.
 */
export function StockBadge({
  signal,
  lang,
  className,
}: {
  signal: StockSignal;
  lang: Lang;
  className?: string;
}) {
  const t = getDictionary(lang);
  const label = {
    in_stock: t.inStock,
    low_stock: t.lowStock,
    out_of_stock: t.outOfStock,
    made_to_order: t.madeToOrder,
    unknown: t.unknownStock,
  }[signal];

  const positive = signal === "in_stock" || signal === "low_stock";

  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
        positive
          ? "bg-ok-bg text-ok"
          : "border border-rule text-ink-muted",
        className,
      )}
    >
      {label}
    </span>
  );
}
