// Shared formatting helpers.

import type { Lang } from "@/lib/i18n";

/**
 * Format a price, showing two decimal places only when the price has a
 * fractional part.
 *
 * Prices are never approximated: a whole-EGP item shows as "EGP 350", while a
 * low-value item (e.g. a resistor at 3.50 EGP) keeps its fractional part rather
 * than rounding to a whole number.
 */
export function formatPrice(price: number, currency: string, lang: Lang): string {
  const hasFraction = !Number.isInteger(price);
  try {
    return new Intl.NumberFormat(lang === "ar" ? "ar-EG" : "en-EG", {
      style: "currency",
      currency,
      minimumFractionDigits: hasFraction ? 2 : 0,
      maximumFractionDigits: 2,
    }).format(price);
  } catch {
    return `${hasFraction ? price.toFixed(2) : price} ${currency}`;
  }
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31536000],
  ["month", 2592000],
  ["week", 604800],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** Human relative time, e.g. "2 days ago" / "منذ يومين". `date` is past-ish. */
export function relativeTime(date: Date, locale: string): string {
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  const diffSeconds = (date.getTime() - Date.now()) / 1000; // negative for the past
  for (const [unit, secs] of UNITS) {
    if (Math.abs(diffSeconds) >= secs) {
      return rtf.format(Math.round(diffSeconds / secs), unit);
    }
  }
  return rtf.format(0, "minute"); // "now"
}
