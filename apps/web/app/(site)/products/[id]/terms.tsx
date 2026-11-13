import { ChevronDown, Globe, Plug } from "lucide-react";

import type { Offer, Variant } from "@/lib/api";
import { formatCount, formatPrice, plural } from "@/lib/format";
import {
  breaksText,
  fitsLabel,
  FITS_INLINE,
  minimumText,
  OPTIONS_SHOWN,
  optionsCurrent,
  optionsInStock,
  priceBreakRows,
  quantityLabel,
} from "@/lib/offers";
import { cn } from "@/lib/utils";

/*
 * The terms a shop states about its listing (docs/PRODUCT.md, Phase 2):
 * options, quantity prices, what it fits, where it ships from. Each piece
 * renders only when the shop states it (C4), and every fold is a `<details>`,
 * so the page works without JavaScript.
 */

/** "9 Nov", or "9 Nov 2025" when not this year. UTC, so server and test agree. */
export function shortDate(value: string | Date | null | undefined, now: Date): string | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const sameYear = date.getUTCFullYear() === now.getUTCFullYear();
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: "UTC",
  });
}

const PILL =
  "inline-flex min-h-[30px] items-center gap-1.5 rounded-full border border-line-strong bg-surface px-[11px] py-1 text-[13px] font-medium text-ink";

/**
 * Neutral pills: "Ships from abroad" and "Fits …". Not the `badge` colours,
 * which mean "N shops". Nothing when the shop states neither.
 */
export function TermPills({ offer, className }: { offer: Offer; className?: string }) {
  const fits = offer.compatible_with ?? [];
  if (!offer.ships_from_abroad && fits.length === 0) return null;
  return (
    <div data-pills className={cn("flex flex-wrap items-start gap-1.5", className)}>
      {offer.ships_from_abroad && <AbroadPill />}
      <FitsPill models={fits} />
    </div>
  );
}

export function AbroadPill() {
  return (
    <span
      data-abroad
      className={PILL}
      title="The shop says this item ships from abroad: delivery may take longer. Ask the shop."
    >
      <Globe aria-hidden="true" className="size-3.5 text-ink-2" />
      Ships from abroad
    </span>
  );
}

/** "Fits K2 Plus" inline; more than two models fold behind "Fits 19 models". */
export function FitsPill({ models }: { models: string[] }) {
  const label = fitsLabel(models);
  if (!label) return null;
  if (models.length <= FITS_INLINE) {
    return (
      <span data-fits className={PILL}>
        <Plug aria-hidden="true" className="size-3.5 shrink-0 text-ink-2" />
        <span dir="auto">{label}</span>
      </span>
    );
  }
  return (
    <details data-fits className="group/fits basis-full">
      <summary
        className={cn(
          PILL,
          // Drawn 30px tall; the invisible band above and below takes a
          // finger's 44px on a phone (S4).
          "relative cursor-pointer list-none group-open/fits:border-ink-2 before:absolute before:inset-x-0 before:-inset-y-2 lg:before:hidden [&::-webkit-details-marker]:hidden",
        )}
      >
        <Plug aria-hidden="true" className="size-3.5 shrink-0 text-ink-2" />
        {label}
        <ChevronDown aria-hidden="true" className="size-4 group-open/fits:rotate-180" />
      </summary>
      <ul className="mt-2 list-none columns-[12rem_2] gap-4 rounded-card border border-line bg-surface px-3 py-2.5 text-[13px] text-ink-2">
        {models.map((model) => (
          <li key={model} dir="auto" className="break-inside-avoid py-0.5">
            {model}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** "Price by quantity, as Giza Robotics lists it": the shop's tiers, no "save x%" (C3). */
export function PriceBreaksTable({ offer, shop }: { offer: Offer; shop: string }) {
  const rows = priceBreakRows(offer);
  if (rows.length === 0) return null;
  return (
    <div data-price-breaks className="mt-1">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-2.5">
        <h3 className="font-sans text-sm font-semibold">Price by quantity</h3>
        <span className="text-[13px] text-ink-2">as {shop} lists it</span>
      </div>
      <div className="overflow-hidden rounded-card border border-line bg-surface">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <Th>Quantity</Th>
              <Th className="text-end">Price</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.from} className="border-b border-line last:border-b-0">
                <td className="px-3 py-2">{quantityLabel(row)}</td>
                <td className="px-3 py-2 text-end whitespace-nowrap">
                  <span className="figure text-[15px] text-ink">
                    {formatPrice(row.price, offer.currency)}
                  </span>{" "}
                  <span className="text-[13px] text-ink-2">each</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      className={cn(
        "border-b border-line bg-ground px-3 py-2 text-start text-xs font-medium text-ink-2",
        className,
      )}
    >
      {children}
    </th>
  );
}

/**
 * Fixed columns, so the rows behind "Show N more" line up with the first six.
 * Narrow price and stock columns on a phone, so the option's name gets the room.
 */
function OptionCols() {
  return (
    <colgroup>
      <col />
      <col className="w-[6.25rem] sm:w-[7.5rem]" />
      <col className="w-[5.5rem] sm:w-[8.5rem]" />
    </colgroup>
  );
}

function OptionRow({
  variant,
  currency,
  stale,
}: {
  variant: Variant;
  currency: string;
  /** Read over 45 days ago: its stock is said quietly, never in bold. */
  stale: boolean;
}) {
  const stock =
    variant.in_stock === true
      ? variant.stock_quantity
        ? `${formatCount(variant.stock_quantity)} in stock`
        : "In stock"
      : variant.in_stock === false
        ? "Out of stock"
        : null;
  return (
    <tr data-option className="border-b border-line last:border-b-0">
      <td dir="auto" className="px-3 py-2 break-words">
        {variant.title}
      </td>
      <td className="px-3 py-2 text-end whitespace-nowrap">
        {variant.price === null ? (
          <span className="text-ink-3">see shop</span>
        ) : (
          <span className="figure text-[15px] text-ink">
            {formatPrice(variant.price, currency)}
          </span>
        )}
      </td>
      <td
        className={cn(
          "px-3 py-2",
          variant.in_stock === true && !stale ? "font-semibold text-ink" : "text-ink-2",
          stock === null && "text-ink-3",
        )}
      >
        {stock ?? "not stated"}
      </td>
    </tr>
  );
}

function OptionTable({
  variants,
  currency,
  stale,
  head = true,
}: {
  variants: Variant[];
  currency: string;
  stale: boolean;
  /** False for the rows behind "Show N more": their head is for screen readers only. */
  head?: boolean;
}) {
  return (
    <table className="w-full table-fixed border-collapse text-sm">
      <OptionCols />
      <thead className={head ? undefined : "sr-only"}>
        <tr>
          <Th>Option</Th>
          <Th className="text-end">Price</Th>
          <Th>Stock</Th>
        </tr>
      </thead>
      <tbody>
        {variants.map((variant, i) => (
          <OptionRow
            key={`${variant.title}-${i}`}
            variant={variant}
            currency={currency}
            stale={stale}
          />
        ))}
      </tbody>
    </table>
  );
}

/**
 * One shop's options, under its buy box: each with its own price and stock,
 * six rows then "Show N more options", and when they were read (they are read
 * once a cycle, so can be older than the price).
 */
export function OptionsSection({ offer, shop, now }: { offer: Offer; shop: string; now: Date }) {
  const variants = offer.variants ?? [];
  if (variants.length === 0) return null;
  const read = shortDate(offer.variants_checked_at, now);
  const first = variants.slice(0, OPTIONS_SHOWN);
  const rest = variants.slice(OPTIONS_SHOWN);
  const unpriced = variants.some((variant) => variant.price === null);
  const stale = !optionsCurrent(offer, now);
  return (
    <section data-options aria-labelledby="options-heading" className="mt-[18px]">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-2.5">
        <h2 id="options-heading" className="text-base lg:text-lg">
          {plural(variants.length, "option")}
        </h2>
        <span className="text-[13px] text-ink-2">
          at {shop}
          {read && (
            <>
              {" · "}
              <span data-options-read className={stale ? "text-age-muted" : undefined}>
                {stale ? `as read ${read}` : `read ${read}`}
              </span>
            </>
          )}
        </span>
      </div>
      <div className="overflow-hidden rounded-card border border-line bg-surface">
        <OptionTable variants={first} currency={offer.currency} stale={stale} />
        {rest.length > 0 && (
          <details data-options-more className="group/more">
            <summary className="flex h-11 cursor-pointer list-none items-center gap-1.5 border-t border-line px-3 text-sm font-medium text-link [&::-webkit-details-marker]:hidden">
              <span className="group-open/more:hidden">
                Show {plural(rest.length, "more option", "more options")}
              </span>
              <span className="hidden group-open/more:inline">Show fewer</span>
              <ChevronDown aria-hidden="true" className="size-4 group-open/more:rotate-180" />
            </summary>
            <div className="border-t border-line">
              <OptionTable variants={rest} currency={offer.currency} stale={stale} head={false} />
            </div>
          </details>
        )}
      </div>
      <p className="mt-1.5 text-[13px] text-ink-2">
        {optionsInStock(offer)} of {variants.length} in stock.
        {unpriced && " “see shop”: the shop shows no separate price for that option."}
        {` Prices and stock as read${read ? ` ${read}` : ""}; confirm on the shop's site.`}
        {stale && " They are over 45 days old, so they set no price on this page."}
      </p>
    </section>
  );
}

/** An offer row's options, folded: "2 options · 1 in stock". */
export function OptionsFold({ offer, now }: { offer: Offer; now: Date }) {
  const variants = offer.variants ?? [];
  if (variants.length === 0) return null;
  const read = shortDate(offer.variants_checked_at, now);
  const stale = !optionsCurrent(offer, now);
  return (
    <details data-options className="group/opts">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1 font-medium text-link lg:min-h-8 [&::-webkit-details-marker]:hidden">
        {plural(variants.length, "option")} · {optionsInStock(offer)} in stock
        <ChevronDown aria-hidden="true" className="size-4 group-open/opts:rotate-180" />
      </summary>
      <div className="mt-1 overflow-hidden rounded-card border border-line bg-surface text-[13px] [&_td]:px-2.5 [&_td]:py-1.5 [&_th]:px-2.5 [&_th]:py-1.5">
        <OptionTable variants={variants} currency={offer.currency} stale={stale} />
      </div>
      {read && (
        <p className={cn("mt-1 text-xs", stale ? "text-age-muted" : "text-ink-3")}>
          Options {stale ? "as read" : "read"} {read}
        </p>
      )}
    </details>
  );
}

/**
 * The facts an offer row adds under its shop, when its shop states them: a
 * stock count, the minimum with its total, quantity prices, "Ships from
 * abroad" and the part number it states; then what it fits (never merged with
 * another row's) and its options. Rows stay self-contained (P3).
 */
export function RowTerms({ offer, now }: { offer: Offer; now: Date }) {
  const bits: { key: string; node: React.ReactNode }[] = [];
  if (offer.stock_quantity && offer.stock_signal !== "out_of_stock") {
    bits.push({ key: "count", node: `${formatCount(offer.stock_quantity)} in stock` });
  }
  const minimum = minimumText(offer);
  if (minimum) bits.push({ key: "minimum", node: minimum });
  const breaks = breaksText(offer);
  if (breaks) bits.push({ key: "breaks", node: breaks });
  if (offer.ships_from_abroad) bits.push({ key: "abroad", node: "Ships from abroad" });
  if (offer.mfr_part_number) {
    bits.push({
      key: "mfr",
      node: (
        <>
          Mfr. part <span data-identifier>{offer.mfr_part_number}</span>
        </>
      ),
    });
  }
  const fits = offer.compatible_with ?? [];
  const options = (offer.variants ?? []).length > 0;
  if (bits.length === 0 && fits.length === 0 && !options) return null;
  return (
    <div data-row-terms className="flex flex-col gap-1.5 text-[13px] text-ink-2 [grid-area:extra]">
      {bits.length > 0 && (
        <p className="flex flex-wrap gap-x-1.5">
          {bits.map((bit, i) => (
            <span key={bit.key} data-term={bit.key}>
              {i > 0 && (
                <span aria-hidden="true" className="me-1.5 text-ink-3">
                  ·
                </span>
              )}
              {bit.node}
            </span>
          ))}
        </p>
      )}
      {fits.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <FitsPill models={fits} />
        </div>
      )}
      <OptionsFold offer={offer} now={now} />
    </div>
  );
}
