/**
 * Prices and counts as text.
 *
 * Built by hand rather than with Intl's currency style: "EGP 260 – 400" is the
 * form the design specifies (rule C3), and Intl would repeat the currency on
 * both ends of a range and vary its spacing by runtime.
 */

const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const FRACTION = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** A bare amount: "1,450", or "3.50" — a resistor is 3.50, never rounded to 4,
 *  and a whole price never grows invented decimals. */
export function formatAmount(amount: number): string {
  return Number.isInteger(amount) ? NUMBER.format(amount) : FRACTION.format(amount);
}

export const PRICE_ON_REQUEST = "Price on request";

/** "EGP 850". */
export function formatPrice(amount: number, currency = "EGP"): string {
  return `${currency} ${formatAmount(amount)}`;
}

/**
 * "EGP 260 – 400" for a range, "EGP 850" when the ends agree or only one is
 * known, and "Price on request" when there is no price at all — which must
 * never read as free.
 *
 * No unit is ever attached: the unit of sale is not recorded, and "EGP 5" next
 * to a 100-pack would imply a per-piece price nobody offered (rule C3).
 */
export function formatPriceRange(
  min: number | null | undefined,
  max?: number | null,
  currency = "EGP",
): string {
  const low = min ?? max;
  if (low === null || low === undefined) return PRICE_ON_REQUEST;
  const high = max ?? low;
  if (high <= low) return formatPrice(low, currency);
  return `${currency} ${formatAmount(low)} – ${formatAmount(high)}`;
}

/** "57,207". */
export function formatCount(count: number): string {
  return NUMBER.format(count);
}

/** "3 shops", "1 shop". */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${formatCount(count)} ${count === 1 ? one : many}`;
}
