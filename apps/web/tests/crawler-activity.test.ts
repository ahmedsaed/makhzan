import { describe, expect, it } from "vitest";

import type { ShopCrawlActivity } from "@/lib/api";
import {
  absoluteTime,
  dayLabel,
  formatCycleDays,
  formatGap,
  formatRequests,
  gapBucketLabel,
  gapRows,
  identityLabel,
  refreshTime,
  relativeTime,
  shopActivityLine,
  sparkline,
} from "@/lib/crawler-activity";

const NOW = new Date("2026-11-09T12:00:00Z");
const hoursAgo = (hours: number) => new Date(NOW.getTime() - hours * 3_600_000);

const SHOP: ShopCrawlActivity = {
  slug: "shop-a",
  name: "Shop A",
  status: "active",
  last_read_at: hoursAgo(3).toISOString(),
  requests_7d: 412,
  requests_7d_partial: false,
  min_gap_s: 15.04,
  median_gap_s: 16,
  requests_by_day: [],
  identity: null,
  last_cycle_days: null,
};

const day = (date: string, requests: number | null) => ({ date, requests });

describe("times", () => {
  it("reads relative, in whole units, either way", () => {
    expect(relativeTime(new Date(NOW.getTime() - 20_000), NOW)).toBe("just now");
    expect(relativeTime(hoursAgo(1 / 60), NOW)).toBe("1 minute ago");
    expect(relativeTime(hoursAgo(3.9), NOW)).toBe("3 hours ago");
    expect(relativeTime(hoursAgo(49), NOW)).toBe("2 days ago");
    expect(relativeTime(hoursAgo(-15), NOW)).toBe("in 15 hours");
  });

  it("gives the absolute time in UTC for the tooltip", () => {
    expect(absoluteTime(new Date("2026-11-09T03:05:00Z"))).toBe("9 Nov 2026, 03:05 UTC");
    expect(refreshTime(3)).toBe("03:00 UTC");
  });
});

describe("figures", () => {
  it("floors a gap: 14.9 s is never published as 15", () => {
    expect(formatGap(14.9)).toBe("14 s");
    expect(formatGap(15.04)).toBe("15 s");
    expect(formatGap(150)).toBe("2 min");
  });

  it("shows an unmeasured gap as a dash", () => {
    expect(formatGap(null)).toBe("—");
    expect(formatGap(undefined)).toBe("—");
  });

  it("marks a request count that is only a floor", () => {
    expect(formatRequests(1412, false)).toBe("1,412");
    expect(formatRequests(1412, true)).toBe("at least 1,412");
    expect(formatRequests(0, true)).toBe("—");
    expect(formatRequests(0, false)).toBe("0");
  });
});

describe("the shop page line", () => {
  it("states when, how many and how far apart", () => {
    expect(shopActivityLine(SHOP, 7, NOW)).toEqual([
      "makhzan read this site 3 hours ago",
      "412 requests in the last 7 days",
      "at least 15 s apart",
    ]);
  });

  it("gives a paused shop one calm sentence and no reason", () => {
    expect(shopActivityLine({ ...SHOP, status: "paused" }, 7, NOW)).toEqual([
      "makhzan is not reading this site at the moment.",
    ]);
  });

  it("leaves out what was not measured", () => {
    expect(
      shopActivityLine({ ...SHOP, min_gap_s: null, requests_7d_partial: true }, 7, NOW),
    ).toEqual(["makhzan read this site 3 hours ago", "at least 412 requests in the last 7 days"]);
    expect(shopActivityLine({ ...SHOP, requests_7d: 0, min_gap_s: null }, 7, NOW)).toEqual([
      "makhzan read this site 3 hours ago",
    ]);
  });

  it("says plainly when the site has never been read", () => {
    expect(shopActivityLine({ ...SHOP, last_read_at: null }, 7, NOW)).toEqual([
      "makhzan has not read this site yet.",
    ]);
  });
});

describe("identity and the last full pass", () => {
  it("names the identity the latest run sent", () => {
    expect(identityLabel({ name: "makhzanbot", signed: true })).toBe("makhzanbot · signed");
    expect(identityLabel({ name: "makhzanbot", signed: false })).toBe("makhzanbot");
    expect(identityLabel({ name: "browser", signed: false })).toBe("browser User-Agent");
    expect(identityLabel(null)).toBeNull();
  });

  it("gives the last full pass in whole days, and nothing before one", () => {
    expect(formatCycleDays(6.5)).toBe("7 days");
    expect(formatCycleDays(6.4)).toBe("6 days");
    expect(formatCycleDays(1.2)).toBe("1 day");
    expect(formatCycleDays(0.4)).toBe("under a day");
    expect(formatCycleDays(null)).toBeNull();
  });
});

describe("requests per day", () => {
  const week = [
    day("2026-11-03", 90),
    day("2026-11-04", 120),
    day("2026-11-05", null),
    day("2026-11-06", 60),
    day("2026-11-07", 0),
    day("2026-11-08", null),
    day("2026-11-09", 30),
  ];

  it("breaks the line at a day not recorded, never drawing it as zero", () => {
    const line = sparkline(week, 56, 18)!;
    // 90 and 120 join; 60 and 0 join; 30 stands alone (both neighbours unknown or the end).
    expect(line.segments).toHaveLength(2);
    expect(line.segments[0].split(" ")).toHaveLength(2);
    expect(line.segments[1].split(" ")).toHaveLength(2);
    expect(line.dots).toHaveLength(1);
    // No point sits on the zero line for an unrecorded day: x of day 3 (index 2) is absent.
    const xs = [...line.segments.join(" ").split(" "), ...line.dots.map((d) => d.join(","))].map(
      (p) => Number(p.split(",")[0]),
    );
    expect(xs).not.toContain(Number((2 + 2 * (52 / 6)).toFixed(1)));
    expect(xs).not.toContain(Number((2 + 5 * (52 / 6)).toFixed(1)));
    // A real zero is drawn at the bottom.
    expect(line.segments[1].split(" ")[1].split(",")[1]).toBe("16");
    expect(line.last).toEqual(line.dots[0]);
  });

  it("says every day in words, the unrecorded ones as such", () => {
    expect(sparkline(week)!.label).toBe(
      "Requests per day, last 7 days. 3 Nov: 90, 4 Nov: 120, 5 Nov: not recorded, 6 Nov: 60, 7 Nov: 0, 8 Nov: not recorded, 9 Nov: 30",
    );
  });

  it("draws nothing when no day recorded a request", () => {
    expect(sparkline([day("2026-11-08", 0), day("2026-11-09", 0)])).toBeNull();
    expect(sparkline([day("2026-11-08", null), day("2026-11-09", null)])).toBeNull();
    expect(sparkline([])).toBeNull();
    expect(dayLabel("2026-11-09")).toBe("9 Nov");
  });
});

describe("the gap histogram", () => {
  const buckets = [
    { min_s: 0, max_s: 14, count: 0 },
    { min_s: 15, max_s: 15, count: 600 },
    { min_s: 16, max_s: 16, count: 200 },
    { min_s: 18, max_s: 19, count: 195 },
    { min_s: 60, max_s: null, count: 5 },
  ];

  it("labels each bucket plainly", () => {
    expect(buckets.map(gapBucketLabel)).toEqual([
      "under 15 s",
      "15 s",
      "16 s",
      "18–19 s",
      "60 s or more",
    ]);
  });

  it("gives shares of every gap, never rounding a few up to nothing or all", () => {
    const rows = gapRows(buckets)!;
    expect(rows.map((r) => r.percent)).toEqual(["0%", "60%", "20%", "20%", "<1%"]);
    expect(rows[0].width).toBe(0);
    expect(rows[1].width).toBe(100);
    expect(rows[4].width).toBe(1.5);
    expect(
      gapRows([
        { min_s: 15, max_s: 15, count: 999 },
        { min_s: 60, max_s: null, count: 1 },
      ])!.map((r) => r.percent),
    ).toEqual([">99%", "<1%"]);
  });

  it("shows nothing when nothing was measured", () => {
    expect(gapRows(null)).toBeNull();
    expect(gapRows([{ min_s: 15, max_s: 15, count: 0 }])).toBeNull();
  });
});
