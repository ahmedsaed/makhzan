/**
 * The privacy page must say what the code does (lib/content/privacy.ts).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ACCESS_LOG_DAYS, BACKUP_DAYS, privacyLead, privacySections } from "@/lib/content/privacy";
import { EMAIL_KEPT_DAYS, IP_HASH_KEPT_HOURS } from "@/lib/report";

const COPY = JSON.stringify([privacyLead, privacySections]);
const ROOT = join(__dirname, "..", "..", "..");

describe("the privacy page", () => {
  it("states purpose, what is kept and for how long", () => {
    expect(COPY).toContain(`Deleted ${EMAIL_KEPT_DAYS} days after you send it.`);
    expect(COPY).toContain(`Deleted after ${IP_HASH_KEPT_HOURS} hours`);
    // Scoped: the reports hold only the scrambled form; the log holds addresses.
    expect(COPY).not.toContain("We never store the address itself");
    expect(COPY).toContain("The reports themselves never hold your address");
    expect(COPY).toContain(`with IP addresses, for ${ACCESS_LOG_DAYS} days, then deletes it`);
    expect(COPY).toMatch(/correct the page/);
    expect(COPY).toMatch(/Law No\. 151 of 2020/);
    expect(COPY).toMatch(/no cookies/i);
  });

  it("keeps the same figures as the worker that enforces them", () => {
    const rules = readFileSync(join(ROOT, "packages/schemas/makhzan_schemas/reports.py"), "utf8");
    expect(rules).toContain(`EMAIL_KEPT = timedelta(days=${EMAIL_KEPT_DAYS})`);
    expect(rules).toContain(`IP_HASH_KEPT = timedelta(hours=${IP_HASH_KEPT_HOURS})`);
  });

  it("says backups may hold it 30 days more, as the backup script prunes", () => {
    expect(COPY).toContain(
      `Copies of the database kept as backups can hold this information for up to ${BACKUP_DAYS} more days before they are deleted.`,
    );
    const prune = readFileSync(join(ROOT, "scripts/lib/prune.sh"), "utf8");
    expect(prune).toContain(`BACKUP_MAX_DAYS=${BACKUP_DAYS}`);
  });

  it("describes itself as the body does: no cookies of ours", () => {
    const page = readFileSync(join(__dirname, "..", "app/(site)/privacy/page.tsx"), "utf8");
    expect(page).toContain("no cookies of ours");
    expect(page).not.toMatch(/No account, no cookies;/);
  });

  it("names Cloudflare as handling every request, reports included", () => {
    expect(COPY).toMatch(/Every visit to makhzan passes through Cloudflare/);
    expect(COPY).toMatch(/Cloudflare handles every request to makhzan, reports included/);
    // Nothing still claims no one else is involved.
    expect(COPY).not.toMatch(/Your report goes only to our server/);
    expect(COPY).not.toMatch(/"No one\./);
  });

  it("keeps the crawling page free of Cloudflare", () => {
    const crawling = readFileSync(join(__dirname, "..", "lib/content/crawling.ts"), "utf8");
    expect(crawling).not.toMatch(/cloudflare/i);
  });

  it("names no address but makhzan's own", () => {
    const addresses = new Set(COPY.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g));
    expect(addresses).toEqual(new Set(["crawler@makhzan.merope.dev"]));
  });
});
