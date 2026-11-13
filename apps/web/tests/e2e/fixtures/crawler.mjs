/**
 * `GET /crawler/activity` for the stub API, shaped like
 * apps/api/app/routers/crawler.py. Fictional shops, matching fixtures/shops.mjs:
 *
 *   - "Shop A" is read daily as makhzanbot, signed, with gaps measured; one
 *     day of its week did not record a count, and its last full pass took
 *     6.4 days;
 *   - "Stale Shop" is paused (the page must say only "Paused", never why); its
 *     last run, long ago, sent the browser User-Agent;
 *   - "New Shop" has a source but has never been read: every figure is empty.
 *
 * Times are relative to the request, so "3 hours ago" holds whatever day the
 * suite runs.
 */

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const ago = (hours) => new Date(Date.now() - hours * HOUR).toISOString();

function nextRun() {
  const next = new Date();
  next.setUTCHours(3, 0, 0, 0);
  if (next.getTime() <= Date.now()) next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString();
}

/** The last 7 UTC days, oldest first, with these counts. */
function week(counts) {
  return counts.map((requests, i) => ({
    date: new Date(Date.now() - (6 - i) * DAY).toISOString().slice(0, 10),
    requests,
  }));
}

export function crawlerActivity() {
  return {
    generated_at: new Date().toISOString(),
    window_days: 7,
    shops: [
      {
        slug: "new-shop",
        name: "New Shop",
        status: "active",
        last_read_at: null,
        requests_7d: 0,
        requests_7d_partial: false,
        min_gap_s: null,
        median_gap_s: null,
        requests_by_day: week([0, 0, 0, 0, 0, 0, 0]),
        identity: null,
        last_cycle_days: null,
      },
      {
        slug: "shop-a",
        name: "Shop A",
        status: "active",
        last_read_at: ago(3),
        requests_7d: 412,
        requests_7d_partial: false,
        min_gap_s: 15.04,
        median_gap_s: 16,
        requests_by_day: week([60, 58, null, 70, 74, 76, 74]),
        identity: { name: "makhzanbot", signed: true },
        last_cycle_days: 6.4,
      },
      {
        slug: "stale-shop",
        name: "Stale Shop",
        status: "paused",
        last_read_at: ago(24 * 80),
        requests_7d: 0,
        requests_7d_partial: false,
        min_gap_s: null,
        median_gap_s: null,
        requests_by_day: week([0, 0, 0, 0, 0, 0, 0]),
        identity: { name: "browser", signed: false },
        last_cycle_days: null,
      },
    ],
    totals: {
      shops: 3,
      shops_active: 2,
      shops_read_7d: 1,
      requests_7d: 412,
      requests_7d_partial: false,
      min_gap_s: 15.04,
      median_gap_s: 16,
      gap_histogram: [
        { min_s: 0, max_s: 14, count: 0 },
        { min_s: 15, max_s: 15, count: 250 },
        { min_s: 16, max_s: 16, count: 80 },
        { min_s: 17, max_s: 17, count: 30 },
        { min_s: 18, max_s: 19, count: 20 },
        { min_s: 20, max_s: 29, count: 25 },
        { min_s: 30, max_s: 59, count: 4 },
        { min_s: 60, max_s: null, count: 2 },
      ],
      robots_txt_honoured: true,
    },
    schedule: { refresh_hour_utc: 3, next_run_at: nextRun() },
  };
}
