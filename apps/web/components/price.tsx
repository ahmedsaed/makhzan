import { formatPriceRange } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A price or a range: "EGP 260 – 400", "EGP 850", or "Price on request".
 *
 * Archivo with tabular figures (rule S3), so prices down a list line up. Size
 * and colour come from the caller; "Price on request" drops to secondary text
 * so it never reads as a number.
 */
export function PriceRange({
  min,
  max = null,
  currency = "EGP",
  className,
}: {
  min: number | null;
  max?: number | null;
  currency?: string;
  className?: string;
}) {
  const known = min !== null || max !== null;
  return (
    <span
      data-price
      className={cn(
        "whitespace-nowrap",
        known ? "figure text-ink" : "font-sans font-medium text-ink-2",
        className,
      )}
    >
      {formatPriceRange(min, max, currency)}
    </span>
  );
}
