import { ChevronDown } from "lucide-react";

import { formatPrice } from "@/lib/format";
import {
  dayMonth,
  HISTORY_DAYS,
  lowestLabel,
  monthTicks,
  priceScale,
  weeksText,
  type History,
  type PriceHistory,
  type Segment,
} from "@/lib/history";
import { cn } from "@/lib/utils";

import { ChartHover, type HoverSegment } from "./history-hover";

/**
 * "Price history": the facts first (now, the lowest and whose it was), a
 * step chart, the 12-week stock strip, how to read it, and the same data as a
 * table. Drawn on the server: the chart is an SVG stretched to its box with
 * non-scaling strokes, and its labels and markers are HTML placed by
 * percentage, so it fits any width without JavaScript and takes the theme's
 * colours from the tokens. The tooltip (ChartHover) is the only part that
 * needs JavaScript, and the table says everything it does.
 *
 * With nothing priced (every shop gives the price on request), only the
 * stock strip, as "Stock history". No history: no card at all (lib/history.ts).
 */
export function PriceHistoryCard({
  history,
  currency,
  shop,
}: {
  history: History;
  currency: string;
  /** The one shop's name, for "Sphinx 3D's price". */
  shop: string | null;
}) {
  const anyShop = history.single ? "" : " (at one shop or more)";
  if (history.kind === "stock") {
    return (
      <section id="history" data-history="stock" aria-labelledby="history-heading" className={CARD}>
        <Header title="Stock history" span="last 12 weeks" />
        <WeekStrip weeks={history.weeks} suffix={anyShop} />
        <p className="mt-2 text-xs text-ink-3">
          No price chart:{" "}
          {history.single ? "the shop gives this price" : "every shop gives its price"} on request,
          and history draws priced offers only.
        </p>
      </section>
    );
  }
  const what = history.single
    ? `${shop ?? "The shop"}'s price${history.each ? " of one" : ""}`
    : `Lowest in-stock price across the shops${history.each ? ", price of one" : ""}`;
  const each = history.each ? (
    <span className="ms-1 text-xs font-medium text-ink-2">each</span>
  ) : null;
  return (
    <section id="history" data-history="price" aria-labelledby="history-heading" className={CARD}>
      <Header
        title="Price history"
        span={history.full ? `last ${HISTORY_DAYS} days` : `since ${dayMonth(history.start)}`}
      />
      <div className="mt-2.5 mb-1.5 flex flex-wrap gap-x-7 gap-y-3">
        <div data-history-now>
          <small className="block text-xs text-ink-2">Now</small>
          {history.now !== null ? (
            <>
              <span className="figure text-xl text-ink">{formatPrice(history.now, currency)}</span>
              {each}
            </>
          ) : (
            <span className="text-sm font-medium text-ink-2">None in stock</span>
          )}
        </div>
        {history.lowest && (
          <div data-history-lowest>
            <small className="block text-xs text-ink-2">{lowestLabel(history)}</small>
            <span className="figure text-xl text-ink">
              {formatPrice(history.lowest.price, currency)}
            </span>
            {each}
            <div className="text-xs text-ink-2">
              {history.lowest.shop
                ? `at ${history.lowest.shop}, ${dayMonth(history.lowest.at)}`
                : dayMonth(history.lowest.at)}
            </div>
          </div>
        )}
      </div>
      <Chart history={history} currency={currency} label={`${what}, step chart`} />
      {history.weeks && <WeekStrip weeks={history.weeks} suffix={anyShop} />}
      <p className="mt-2 text-xs text-ink-3">
        {what}. makhzan records a point only when a price or stock changes
        {history.full
          ? ""
          : `; recording began ${dayMonth(history.start)}, so there are fewer than ${HISTORY_DAYS} days yet`}
        . {history.single ? "Dashed: out of stock." : "Shaded: no shop in stock."} Offers on request
        are not drawn.
      </p>
      <HistoryTable history={history} currency={currency} />
    </section>
  );
}

const CARD =
  "mt-6 scroll-mt-20 rounded-card border border-line bg-surface p-3.5 lg:mt-5 lg:p-4.5 min-w-0";

function Header({ title, span }: { title: string; span: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-2.5">
      <h2 id="history-heading" className="text-base lg:text-lg">
        {title}
      </h2>
      <span className="text-[13px] text-ink-2">{span}</span>
    </div>
  );
}

function WeekStrip({ weeks, suffix }: { weeks: boolean[]; suffix: string }) {
  const text = weeksText(weeks);
  return (
    <div data-weeks className="mt-2.5 flex flex-wrap items-center gap-2.5 text-[13px] text-ink-2">
      <span aria-hidden="true" className="flex gap-[3px]">
        {weeks.map((on, i) => (
          <i
            key={i}
            title={`Week ${i + 1}: ${on ? "in stock" : "out of stock"}`}
            className={cn(
              "block size-3 rounded-[3px] border-[1.5px]",
              on ? "border-ink-2 bg-ink-2" : "border-ink-3",
            )}
          />
        ))}
      </span>
      <span>
        {text.charAt(0).toUpperCase() + text.slice(1)}
        {suffix}
      </span>
    </div>
  );
}

/** viewBox units of the plot: x and y both 0–1000, stretched to the box. */
const U = 1000;

function Chart({
  history,
  currency,
  label,
}: {
  history: PriceHistory;
  currency: string;
  label: string;
}) {
  const { start, end, segments } = history;
  const { lo, hi, ticks } = priceScale(segments);
  const x = (t: number) => ((t - start) / (end - start)) * U;
  const y = (v: number) => ((hi - v) / (hi - lo)) * U;
  const pct = (n: number) => `${(n / U) * 100}%`;
  const lowest = history.lowest;
  const last = segments[segments.length - 1];
  const hover: HoverSegment[] = segments.map((s) => ({
    from: x(s.from) / U,
    to: x(s.to) / U,
    top: s.price === null ? 0.5 : y(s.price) / U,
    date: dayMonth(s.from),
    text:
      s.price === null
        ? history.single
          ? "No price"
          : "No shop in stock"
        : `${formatPrice(s.price, currency)}${history.each ? " each" : ""}${s.inStock ? "" : " · out of stock"}`,
    shop: s.shop,
  }));
  return (
    <div data-chart className="relative mt-1.5 h-[150px] text-[11px] text-ink-3">
      {/* Price labels */}
      <div aria-hidden="true" className="absolute top-2.5 bottom-[22px] left-0 w-10">
        {ticks.map((tick) => (
          <span
            key={tick}
            className="absolute right-0 -translate-y-1/2 tabular"
            style={{ top: pct(y(tick)) }}
          >
            {tickLabel(tick)}
          </span>
        ))}
      </div>
      {/* Month labels */}
      <div aria-hidden="true" className="absolute right-2 bottom-0 left-[46px] h-[22px]">
        {monthTicks(start, end).map((tick) => (
          <span
            key={tick.at}
            className="absolute bottom-1 -translate-x-1/2"
            style={{ left: pct(x(tick.at)) }}
          >
            {tick.label}
          </span>
        ))}
      </div>
      <ChartHover segments={hover} className="absolute top-2.5 right-2 bottom-[22px] left-[46px]">
        <svg
          role="img"
          aria-label={label}
          viewBox={`0 0 ${U} ${U}`}
          preserveAspectRatio="none"
          className="absolute inset-0 size-full overflow-visible"
        >
          {ticks.map((tick) => (
            <line
              key={tick}
              x1={0}
              x2={U}
              y1={y(tick)}
              y2={y(tick)}
              className="stroke-line"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {segments.map((s, i) =>
            s.price === null ? (
              <rect
                key={i}
                data-gap
                x={x(s.from)}
                y={0}
                width={Math.max(0, x(s.to) - x(s.from))}
                height={U}
                className="fill-line opacity-70"
              />
            ) : (
              <Step key={i} segment={s} next={segments[i + 1]} x={x} y={y} />
            ),
          )}
        </svg>
        {segments.map((s, i) =>
          s.price === null && x(s.to) - x(s.from) > 80 ? (
            <span
              key={i}
              aria-hidden="true"
              className="absolute top-1 -translate-x-1/2 text-[10px] whitespace-nowrap text-ink-2"
              style={{ left: pct((x(s.from) + x(s.to)) / 2) }}
            >
              {history.single ? "no price" : "none in stock"}
            </span>
          ) : null,
        )}
        {lowest && (
          <Dot
            data="lowest"
            left={pct(x(lowest.at))}
            top={pct(y(lowest.price))}
            className="bg-link"
          />
        )}
        {last.price !== null && (
          <Dot data="now" left="100%" top={pct(y(last.price))} className="bg-surface" />
        )}
      </ChartHover>
    </div>
  );
}

function Step({
  segment,
  next,
  x,
  y,
}: {
  segment: Segment;
  next?: Segment;
  x: (t: number) => number;
  y: (v: number) => number;
}) {
  const price = segment.price as number;
  return (
    <>
      <line
        data-step={segment.inStock ? "in" : "out"}
        x1={x(segment.from)}
        x2={x(segment.to)}
        y1={y(price)}
        y2={y(price)}
        className={segment.inStock ? "stroke-link" : "stroke-ink-3"}
        strokeWidth={2}
        strokeDasharray={segment.inStock ? undefined : "4 4"}
        vectorEffect="non-scaling-stroke"
      />
      {next && next.price !== null && (
        <line
          x1={x(segment.to)}
          x2={x(segment.to)}
          y1={y(price)}
          y2={y(next.price)}
          className="stroke-line-strong"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      )}
    </>
  );
}

function Dot({
  data,
  left,
  top,
  className,
}: {
  data: string;
  left: string;
  top: string;
  className: string;
}) {
  return (
    <span
      aria-hidden="true"
      data-dot={data}
      className={cn(
        "pointer-events-none absolute size-[11px] -translate-x-1/2 -translate-y-1/2 rounded-full border-2",
        data === "now" ? "border-link" : "border-surface",
        className,
      )}
      style={{ left, top }}
    />
  );
}

function tickLabel(value: number): string {
  if (value < 10) return value.toFixed(2);
  return Math.round(value).toLocaleString("en-US");
}

function HistoryTable({ history, currency }: { history: PriceHistory; currency: string }) {
  return (
    <details data-history-table className="group/table">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1 text-[13px] text-link lg:mt-1.5 lg:min-h-0 [&::-webkit-details-marker]:hidden">
        <span className="group-open/table:hidden">Show as a table</span>
        <span className="hidden group-open/table:inline">Hide the table</span>
        <ChevronDown aria-hidden="true" className="size-4 group-open/table:rotate-180" />
      </summary>
      <div className="mt-1 overflow-hidden rounded-card border border-line bg-surface">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="[&_th]:border-b [&_th]:border-line [&_th]:bg-ground [&_th]:px-3 [&_th]:py-2 [&_th]:text-start [&_th]:text-xs [&_th]:font-medium [&_th]:text-ink-2">
              <th>From</th>
              <th className="text-end!">Price</th>
              <th>Stock</th>
              {!history.single && <th>Shop</th>}
            </tr>
          </thead>
          <tbody>
            {history.segments.map((s) => (
              <tr
                key={s.from}
                className="border-b border-line last:border-b-0 [&_td]:px-3 [&_td]:py-2"
              >
                <td>{dayMonth(s.from)}</td>
                <td className="text-end whitespace-nowrap">
                  {s.price === null ? (
                    "—"
                  ) : (
                    <span className="figure text-ink">{formatPrice(s.price, currency)}</span>
                  )}
                </td>
                <td>
                  {s.price === null
                    ? history.single
                      ? "Price on request"
                      : "None in stock"
                    : s.inStock
                      ? "In stock"
                      : "Out of stock"}
                </td>
                {!history.single && <td>{s.shop ?? "—"}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/**
 * The facts line under the title: "Lowest in 90 days EGP 1,650 · in stock 10
 * of the last 12 weeks · Price history", or "in stock 11 of the last 12 weeks
 * · Stock history" with nothing priced.
 */
export function historyFactParts(
  history: History,
  currency: string,
): { lowest: string | null; weeks: string | null; link: string } {
  if (history.kind === "stock") {
    return { lowest: null, weeks: weeksText(history.weeks), link: "Stock history" };
  }
  return {
    lowest: history.lowest
      ? `${lowestLabel(history)} ${formatPrice(history.lowest.price, currency)}${history.each ? " each" : ""}`
      : null,
    weeks: history.weeks ? weeksText(history.weeks) : null,
    link: "Price history",
  };
}
