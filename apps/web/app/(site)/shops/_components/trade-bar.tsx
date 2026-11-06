import type { TradeShare } from "@/lib/shops";
import { cn } from "@/lib/utils";

/** Bar segments, largest first. Opacity steps of the one accent rather than new
 *  colours: the palette has none to spare, and order already says which is which. */
const SEGMENT = ["bg-action", "bg-action/55", "bg-action/30", "bg-ink-3/40"];

/**
 * A shop's catalogue by trade as one thin bar. Decoration only: the same
 * numbers are always in words beside it, which is what a screen reader gets.
 */
export function TradeBar({ shares, className }: { shares: TradeShare[]; className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("flex h-2 overflow-hidden rounded-full bg-line", className)}
    >
      {shares.map((share, index) => (
        <span
          key={share.domain ?? "other"}
          className={SEGMENT[Math.min(index, SEGMENT.length - 1)]}
          style={{ width: `${share.percent}%` }}
        />
      ))}
    </div>
  );
}
