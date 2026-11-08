import type { CrawlerActivity, ShopCrawlActivity } from "@/lib/api";
import type { ActivityContent } from "@/lib/content/crawling";
import {
  absoluteTime,
  formatGap,
  formatRequests,
  parseTime,
  refreshTime,
  relativeTime,
  STATUS_LABEL,
} from "@/lib/crawler-activity";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * "Crawler activity" on /how-we-crawl (`#activity`): per shop, when we last
 * read its site, how many requests we sent this week and how far apart they
 * were, with the totals above. The proof of the policy written above it.
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
      className="mt-8 scroll-mt-6"
    >
      <h2 id="activity-heading" className="text-lg text-ink">
        {content.heading}
      </h2>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-2">{content.lead}</p>

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
              </th>
              <td className={cn(cell, figure, "text-ink-2")}>
                <When value={shop.last_read_at} now={now} empty="Not yet" />
              </td>
              <td className={cn(cell, figure, "text-right text-ink tabular")}>
                {formatRequests(shop.requests_7d, shop.requests_7d_partial)}
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
            <p className="min-w-0 font-medium break-words text-ink">{shop.name}</p>
            <Status status={shop.status} />
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1.5 text-sm">
            <Fact label="Last read">
              <When value={shop.last_read_at} now={now} empty="Not yet" />
            </Fact>
            <Fact label={`Requests, ${days} days`}>
              {formatRequests(shop.requests_7d, shop.requests_7d_partial)}
            </Fact>
            <Fact label="Shortest gap">{formatGap(shop.min_gap_s)}</Fact>
            <Fact label="Typical gap">{formatGap(shop.median_gap_s)}</Fact>
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
