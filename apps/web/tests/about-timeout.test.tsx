/**
 * About's live counts give up on a hung API: with an empty cache, a /stats or
 * /categories that never answers must cost the page its timeout and the fixed
 * wording, not hold it. The timeout is opt-in in lib/api.ts, so every other
 * caller keeps waiting as before.
 */
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchCategories, fetchStats } from "@/lib/api";
import { CATALOGUE_FALLBACK } from "@/lib/content/about";

/** A fetch that never answers, and rejects only when its signal aborts, as a
 *  real fetch does. */
function hungFetch() {
  return vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
    return new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(init.signal!.reason));
    });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the API client's timeout", () => {
  it("rejects a hung call once the timeout passes", async () => {
    vi.stubGlobal("fetch", hungFetch());
    const started = Date.now();
    await expect(fetchStats({ timeoutMs: 50 })).rejects.toBeTruthy();
    await expect(fetchCategories(undefined, { timeoutMs: 50 })).rejects.toBeTruthy();
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("is opt-in: without one, no signal is sent", async () => {
    const fetch = vi.fn(async () => Response.json({ products: 1, suppliers: 1, categories: 1 }));
    vi.stubGlobal("fetch", fetch);
    await fetchStats();
    await fetchCategories("electronics");
    for (const [, init] of fetch.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.signal).toBeUndefined();
    }
  });
});

describe("the about page on a hung API", () => {
  it("falls back to the fixed wording within its 3 s timeout", { timeout: 10_000 }, async () => {
    const fetch = hungFetch();
    vi.stubGlobal("fetch", fetch);
    const { default: AboutPage } = await import("@/app/(site)/about/page");

    const started = Date.now();
    render(await AboutPage());
    const elapsed = Date.now() - started;

    expect(document.querySelector("[data-catalogue-size]")).toHaveTextContent(CATALOGUE_FALLBACK);
    expect(elapsed).toBeGreaterThanOrEqual(2900);
    expect(elapsed).toBeLessThan(4500);
    const paths = fetch.mock.calls.map(([input]) => new URL(String(input)).pathname);
    expect(paths.sort()).toEqual(["/categories", "/stats"]);
  });
});
