/**
 * The privacy page must say what the code does (lib/content/privacy.ts).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { privacyLead, privacySections } from "@/lib/content/privacy";
import { EMAIL_KEPT_DAYS, IP_HASH_KEPT_HOURS } from "@/lib/report";

const COPY = JSON.stringify([privacyLead, privacySections]);
const ROOT = join(__dirname, "..", "..", "..");

describe("the privacy page", () => {
  it("states purpose, what is kept and for how long", () => {
    expect(COPY).toContain(`Deleted ${EMAIL_KEPT_DAYS} days after we close the report`);
    expect(COPY).toContain(`Deleted after ${IP_HASH_KEPT_HOURS} hours`);
    expect(COPY).toContain("We never store the address itself");
    expect(COPY).toMatch(/correct the page/);
    expect(COPY).toMatch(/Law No\. 151 of 2020/);
    expect(COPY).toMatch(/no cookies/i);
  });

  it("keeps the same figures as the worker that enforces them", () => {
    const rules = readFileSync(join(ROOT, "packages/schemas/makhzan_schemas/reports.py"), "utf8");
    expect(rules).toContain(`EMAIL_KEPT_AFTER_CLOSED = timedelta(days=${EMAIL_KEPT_DAYS})`);
    expect(rules).toContain(`IP_HASH_KEPT = timedelta(hours=${IP_HASH_KEPT_HOURS})`);
  });

  it("does not mention Cloudflare", () => {
    expect(COPY).not.toMatch(/cloudflare/i);
  });

  it("names no address but makhzan's own", () => {
    const addresses = new Set(COPY.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g));
    expect(addresses).toEqual(new Set(["crawler@makhzan.merope.dev"]));
  });
});
