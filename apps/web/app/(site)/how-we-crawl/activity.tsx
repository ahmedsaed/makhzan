import type { CrawlerActivity, ShopCrawlActivity } from "@/lib/api";
import type { ActivityContent } from "@/lib/content/crawling";
import {
  absoluteTime,
  formatCycleDays,
  formatGap,
  formatRequests,
  gapRows,
  identityLabel,
  parseTime,
  refreshTime,
  relativeTime,
  sparkline,
  STATUS_LABEL,
} from "@/lib/crawler-activity";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * "Crawler activity" on /how-we-crawl (`#activity`): per shop, when we last
 * read its site and how long its last full pass took, how many requests we
 * sent this week (with a line of them per day), how far apart they were and
 * who we said we were, with the totals above and every shop's gaps together
 * below. The proof of the policy written above it.
 *
 * A table from `md`; stacked cards on phones, which never scroll sideways.
 * Only neutral words: a paused shop is "Paused", with no reason.
 */
export function CrawlerActivitySection({
  activity,
  content,
  now,
}: {
  activity: CrawlerActivity | null;
  content: ActivityContent;
  now: Date;
}) {
  return (
    <section
      id="activity"
      aria-labelledby="activity-heading"
      data-crawler-activity
      className="scroll-mt-[72px] pt-9 lg:scroll-mt-6"
    >
      <h2 id="activity-heading" className="text-[22px] text-ink">
        {content.heading}
      </h2>
      <p className="mt-1.5 max-w-2xl text-[15px] text-ink-2">{content.lead}</p>

      {activity ? (
        <>
          <Totals activity={activity} content={content} now={now} />
          {activity.shops.length > 0 && (
            <>
              <ShopTable shops={activity.shops} days={activity.window_days} now={now} />
              <ShopCards shops={activity.shops} days={activity.window_days} now={now} />
            </>
          )}
          <p className="mt-3 text-[13px] leading-relaxed text-ink-2">{content.gapNote}</p>
          <GapHistogram activity={activity} content={content} />
        </>
      ) : (
        <p
          data-activity-unavailable
          className="mt-4 rounded-card border border-line bg-surface p-4 text-[15px] text-ink-2"
        >
          {content.unavailable}
        </p>
      )}
    </section>
  );
}

function When({ value, now, empty }: { value: string | null; now: Date; empty: string }) {
  const date = parseTime(value);
  if (!date) return <span className="text-ink-3">{empty}</span>;
  return (
    <time dateTime={date.toISOString()} title={absoluteTime(date)}>
      {relativeTime(date, now)}
    </time>
  );
}

function Totals({
  activity,
  content,
  now,
}: {
  activity: CrawlerActivity;
  content: ActivityContent;
  now: Date;
}) {
  const { totals, schedule } = activity;
  const next = parseTime(schedule.next_run_at);
  return (
    <dl data-activity-totals className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
      <Tile label="Shops read this week">
        {formatCount(totals.shops_read_7d)}
        <span className="text-ink-2"> of {formatCount(totals.shops)}</span>
      </Tile>
      <Tile label="Requests this week">
        {formatRequests(totals.requests_7d, totals.requests_7d_partial)}
      </Tile>
      <Tile
        label="Next daily run"
        note={`Early morning, Egypt time (${refreshTime(schedule.refresh_hour_utc)})`}
      >
        {next ? (
          <time dateTime={next.toISOString()} title={absoluteTime(next)}>
            {relativeTime(next, now)}
          </time>
        ) : (
          <span className="text-[15px] text-ink-2">{content.noNextRun}</span>
        )}
      </Tile>
      <Tile label="robots.txt">Honoured</Tile>
    </dl>
  );
}

function Tile({
  label,
  note,
  children,
}: {
  label: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-control border border-line bg-surface p-2.5">
      <dt className="text-xs text-ink-2">{label}</dt>
      <dd className="mt-0.5 figure text-[17px] leading-tight text-ink">{children}</dd>
      {note && <dd className="mt-1 text-xs leading-snug text-ink-2">{note}</dd>}
    </div>
  );
}

function Status({ status }: { status: ShopCrawlActivity["status"] }) {
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex items-center rounded-full px-2 text-[13px] font-medium",
        status === "active" ? "bg-ground text-ink" : "bg-ground text-ink-2",
      )}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

/** Desktop and tablets: one row per shop. */
function ShopTable({ shops, days, now }: { shops: ShopCrawlActivity[]; days: number; now: Date }) {
  const heading = "px-3 py-2 text-left text-xs font-semibold text-ink-2";
  const cell = "px-3 py-2.5 align-top";
  // Figures and times stay on one line; only a long shop name wraps.
  const figure = "whitespace-nowrap";
  return (
    <div className="mt-4 hidden overflow-hidden rounded-card border border-line bg-surface md:block">
      <table className="w-full text-sm">
        <thead className="border-b border-line">
          <tr>
            <th scope="col" className={heading}>
              Shop
            </th>
            <th scope="col" className={heading}>
              Last read
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              Requests, {days} days
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              Shortest gap
            </th>
            <th scope="col" className={cn(heading, "text-right")}>
              Typical gap
            </th>
            <th scope="col" className={heading}>
              Status
            </th>
          </tr>
        </thead>
        <tbody>
          {shops.map((shop) => (
            <tr
              key={shop.slug}
              data-activity-shop={shop.slug}
              className="border-b border-line last:border-b-0"
            >
              <th scope="row" className={cn(cell, "text-left font-medium text-ink")}>
                {shop.name}
                <Identity identity={shop.identity} />
              </th>
              <td className={cn(cell, figure, "text-ink-2")}>
                <When value={shop.last_read_at} now={now} empty="Not yet" />
                <LastPass days={shop.last_cycle_days} />
              </td>
              <td className={cn(cell, figure, "text-right text-ink tabular")}>
                {formatRequests(shop.requests_7d, shop.requests_7d_partial)}
                <Spark days={shop.requests_by_day} />
              </td>
              <td className={cn(cell, figure, "text-right text-ink tabular")}>
                {formatGap(shop.min_gap_s)}
              </td>
              <td className={cn(cell, figure, "text-right text-ink tabular")}>
                {formatGap(shop.median_gap_s)}
              </td>
              <td className={cell}>
                <Status status={shop.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Phones: a card per shop, the same facts as the table's row. */
function ShopCards({ shops, days, now }: { shops: ShopCrawlActivity[]; days: number; now: Date }) {
  return (
    <ul className="mt-4 flex flex-col gap-2 md:hidden">
      {shops.map((shop) => (
        <li
          key={shop.slug}
          data-activity-shop={shop.slug}
          className="rounded-card border border-line bg-surface p-3"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="min-w-0 font-medium break-words text-ink">
              {shop.name}
              <Identity identity={shop.identity} />
            </p>
            <Status status={shop.status} />
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
            <Fact label="Last read">
              <When value={shop.last_read_at} now={now} empty="Not yet" />
            </Fact>
            <Fact label={`Requests, ${days} days`}>
              {formatRequests(shop.requests_7d, shop.requests_7d_partial)}
              <Spark days={shop.requests_by_day} />
            </Fact>
            <Fact label="Shortest gap">{formatGap(shop.min_gap_s)}</Fact>
            <Fact label="Typical gap">{formatGap(shop.median_gap_s)}</Fact>
            <Fact label="Last full pass">{formatCycleDays(shop.last_cycle_days) ?? "—"}</Fact>
          </dl>
        </li>
      ))}
    </ul>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-2">{label}</dt>
      <dd className="text-ink tabular">{children}</dd>
    </div>
  );
}

/** Who the shop's latest run said it was, under its name. */
function Identity({ identity }: { identity: ShopCrawlActivity["identity"] | undefined }) {
  const label = identityLabel(identity);
  if (!label) return null;
  const bot = identity?.name === "makhzanbot";
  return (
    <span
      data-identity={identity?.name}
      className={cn(
        "mt-0.5 block w-fit rounded-full border px-1.5 text-[11.5px] font-medium whitespace-nowrap",
        bot
          ? "border-transparent bg-badge text-badge-ink"
          : "border-dashed border-line-strong text-ink-2",
      )}
    >
      {label}
    </span>
  );
}

function LastPass({ days }: { days: number | null | undefined }) {
  const text = formatCycleDays(days);
  if (!text) return null;
  return (
    <span data-last-pass className="block text-xs text-ink-3">
      last full pass: {text}
    </span>
  );
}

/** Requests per day over the window, beside the count. A day whose count was
 *  not recorded breaks the line rather than dropping it to zero. */
function Spark({ days }: { days: ShopCrawlActivity["requests_by_day"] | undefined }) {
  const width = 56;
  const height = 18;
  const line = sparkline(days, width, height);
  if (!line) return null;
  return (
    <svg
      data-sparkline
      role="img"
      aria-label={line.label}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="ml-1.5 inline-block align-middle"
    >
      <line x1="0" y1={height - 1} x2={width} y2={height - 1} className="stroke-line-strong" />
      {line.segments.map((points) => (
        <polyline
          key={points}
          points={points}
          fill="none"
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
          className="stroke-link"
        />
      ))}
      {line.dots.map(([x, y]) => (
        <circle key={`${x},${y}`} cx={x} cy={y} r="1.5" className="fill-link" />
      ))}
      <circle cx={line.last[0]} cy={line.last[1]} r="2" className="fill-link" />
    </svg>
  );
}

/** Every gap of the week, all shops together, as horizontal bars. */
function GapHistogram({
  activity,
  content,
}: {
  activity: CrawlerActivity;
  content: ActivityContent;
}) {
  const rows = gapRows(activity.totals.gap_histogram);
  if (!rows) return null;
  return (
    <div data-gap-histogram className="mt-3.5 rounded-card border border-line bg-surface p-4">
      <h3 className="text-base text-ink">{content.histogramHeading}</h3>
      <p className="mt-1 text-[13.5px] text-ink-2">{content.histogramLead}</p>
      <dl className="mt-2.5 flex flex-col gap-1.5">
        {rows.map((row) => (
          <div
            key={row.label}
            className="grid grid-cols-[5.5rem_minmax(0,1fr)_3rem] items-center gap-2 text-[13px] text-ink-2"
          >
            <dt>{row.label}</dt>
            <dd aria-hidden="true">
              <i className="block h-3.5 rounded-sm bg-action" style={{ width: `${row.width}%` }} />
            </dd>
            <dd className="text-right text-ink tabular">{row.percent}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
