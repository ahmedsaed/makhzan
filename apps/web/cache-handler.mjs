// Next's own file-system cache, with two changes for the cached (ISR) product
// pages: one older than PAGE_MAX_AGE is never served, and once an hour such
// pages are deleted from disk.
//
// Next serves a stale ISR page once more however old it is, and renders the
// fresh one in the background. `expireTime` (next.config.ts) does not change
// that. It only sets the stale-while-revalidate a CDN is told. A product page
// nobody opened for three weeks would then show "checked 2 days ago" and the
// wrong 45-day stale fold (C2b) to its next visitor. Here such a copy counts
// as missing and is rendered afresh first, so that error is at most a day.
//
// Next never deletes a cached page either. One product page is about 0.6 MB on
// disk (HTML, RSC payload and its segments), so 60k products would come to
// about 36 GB. A page over PAGE_MAX_AGE is never served, so deleting it loses
// nothing, and the disk holds about one day's distinct product pages.
//
// The base class is internal to Next, not a public API. next is pinned to an
// exact version in package.json; on an upgrade, check that this import path,
// the entry's shape (`value.kind`, `lastModified`) and the file layout
// (`<id>.html`, `.rsc`, `.meta`, `.segments/`) still hold.
import { readdir, rm, stat } from "node:fs/promises";
import path from "node:path";

import fileSystemCache from "next/dist/server/lib/incremental-cache/file-system-cache.js";

const FileSystemCache = fileSystemCache.default ?? fileSystemCache;

/** Seconds. Also next.config.ts's `expireTime`, so a CDN keeps no copy longer. */
export const PAGE_MAX_AGE = 86400;

const PRUNE_EVERY_MS = 3600 * 1000;

/** True for a cached page (not fetched data) rendered more than `PAGE_MAX_AGE` ago. */
export function tooOld(entry, now = Date.now()) {
  return (
    entry?.value?.kind === "APP_PAGE" &&
    entry.lastModified > 0 &&
    now - entry.lastModified > PAGE_MAX_AGE * 1000
  );
}

/**
 * Deletes every page in `dir` whose HTML was written over `PAGE_MAX_AGE` ago,
 * with its RSC payload, metadata and segments. Only the products directory:
 * it holds nothing from the build (generateStaticParams returns none), while
 * the rest of .next/server/app is the build's own and older than a day.
 */
export async function prune(dir, now = Date.now()) {
  const names = await readdir(dir).catch(() => []);
  for (const name of names) {
    if (!name.endsWith(".html")) continue;
    const page = path.join(dir, name.slice(0, -".html".length));
    const { mtimeMs } = await stat(`${page}.html`).catch(() => ({ mtimeMs: now }));
    if (now - mtimeMs <= PAGE_MAX_AGE * 1000) continue;
    for (const suffix of [".html", ".rsc", ".meta", ".segments"]) {
      await rm(`${page}${suffix}`, { recursive: true, force: true });
    }
  }
}

let lastPrune = 0;

export default class BoundedAgeCache extends FileSystemCache {
  async get(...args) {
    const entry = await super.get(...args);
    return tooOld(entry) ? null : entry;
  }

  async set(...args) {
    await super.set(...args);
    const now = Date.now();
    if (this.serverDistDir && now - lastPrune > PRUNE_EVERY_MS) {
      lastPrune = now;
      prune(path.join(this.serverDistDir, "app", "products"), now).catch(console.error);
    }
  }
}
