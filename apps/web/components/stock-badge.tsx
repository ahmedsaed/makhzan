import type { StockSignal } from "@/lib/api";
import { cn } from "@/lib/utils";

const LABELS: Record<StockSignal, string> = {
  in_stock: "In stock",
  low_stock: "Low stock",
  out_of_stock: "Out of stock",
  made_to_order: "Made to order",
  unknown: "Availability unknown",
};

/**
 * Availability is a hint, never a stock count — suppliers publish a state, not a
 * number. "Unknown" is rendered rather than hidden: a shop that says nothing is
 * different from one that says out of stock.
 *
 * No colour of its own: the palette has none to spare for stock, and weight
 * separates "in stock" from the rest well enough.
 */
export function StockBadge({ signal, className }: { signal: StockSignal; className?: string }) {
  const positive = signal === "in_stock" || signal === "low_stock";
  return (
    <span
      className={cn(
        "text-[13px]",
        positive ? "font-semibold text-ink" : "text-ink-2",
        className,
      )}
    >
      {LABELS[signal]}
    </span>
  );
}
