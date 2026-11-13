// @vitest-environment node
import { mkdir, mkdtemp, readdir, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import BoundedAgeCache, { PAGE_MAX_AGE, prune, tooOld } from "@/cache-handler.mjs";
import nextConfig from "@/next.config";

const DAY_MS = PAGE_MAX_AGE * 1000;
const NOW = Date.UTC(2026, 10, 13, 12);

describe("the product page cache", () => {
  it("never serves a page rendered over a day ago", () => {
    const page = (age: number) => ({ lastModified: NOW - age, value: { kind: "APP_PAGE" } });
    expect(tooOld(page(DAY_MS - 1000), NOW)).toBe(false);
    expect(tooOld(page(DAY_MS + 1000), NOW)).toBe(true);
  });

  it("leaves fetched data to its own lifetime", () => {
    expect(tooOld({ lastModified: NOW - 7 * DAY_MS, value: { kind: "FETCH" } }, NOW)).toBe(false);
    expect(tooOld(null, NOW)).toBe(false);
  });

  it("tells a CDN the same day", () => {
    expect(nextConfig.expireTime).toBe(PAGE_MAX_AGE);
    expect(nextConfig.cacheHandler).toMatch(/cache-handler\.mjs$/);
    expect(typeof BoundedAgeCache).toBe("function");
  });
});

describe("pruning cached pages from disk", () => {
  let dir: string;

  async function page(id: string, ageMs: number) {
    const base = path.join(dir, id);
    await mkdir(`${base}.segments`, { recursive: true });
    await writeFile(`${base}.segments/_tree.segment.rsc`, "");
    for (const suffix of [".html", ".rsc", ".meta"]) await writeFile(`${base}${suffix}`, "");
    const at = new Date(NOW - ageMs);
    await utimes(`${base}.html`, at, at);
  }

  beforeEach(async () => {
    dir = await mkdtemp(path.join(tmpdir(), "isr-"));
  });
  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("deletes every file of a page over a day old, and keeps the rest", async () => {
    await page("old", DAY_MS + 60_000);
    await page("fresh", DAY_MS - 60_000);
    await prune(dir, NOW);
    expect((await readdir(dir)).sort()).toEqual([
      "fresh.html",
      "fresh.meta",
      "fresh.rsc",
      "fresh.segments",
    ]);
  });

  it("does nothing when no page has been cached yet", async () => {
    await expect(prune(path.join(dir, "missing"), NOW)).resolves.toBeUndefined();
  });
});
