/**
 * `GET /crawler/activity` for the stub API, shaped like
 * apps/api/app/routers/crawler.py. Fictional shops, matching fixtures/shops.mjs:
 *
 *   - "Shop A" is read daily, with gaps measured;
 *   - "Stale Shop" is paused (the page must say only "Paused", never why);
 *   - "New Shop" has a source but has never been read: every figure is empty.
 *
 * Times are relative to the request, so "3 hours ago" holds whatever day the
 * suite runs.
 */

const HOUR = 3_600_000;
const ago = (hours) => new Date(Date.now() - hours * HOUR).toISOString();

function nextRun() {
  const next = new Date();
  next.setUTCHours(3, 0, 0, 0);
  if (next.getTime() <= Date.now()) next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString();
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
      robots_txt_honoured: true,
    },
    schedule: { refresh_hour_utc: 3, next_run_at: nextRun() },
  };
}
