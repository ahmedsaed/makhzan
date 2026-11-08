import { describe, expect, it } from "vitest";

import type { ShopCrawlActivity } from "@/lib/api";
import {
  absoluteTime,
  formatGap,
  formatRequests,
  refreshTime,
  relativeTime,
  shopActivityLine,
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
};

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
