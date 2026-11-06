import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * "3 shops". Being sold by several shops is rare (1.4% of products), so it is
 * a badge rather than a column — and the one place the badge colours are used.
 */
export function ShopsBadge({ count, className }: { count: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full bg-badge px-2 font-semibold whitespace-nowrap text-badge-ink",
        className,
      )}
    >
      {plural(count, "shop")}
    </span>
  );
}
