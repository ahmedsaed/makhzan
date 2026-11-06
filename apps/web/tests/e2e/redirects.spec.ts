import { expect, test } from "@playwright/test";

/**
 * The previous site's URLs were shared, bookmarked and indexed. Each still has
 * an equivalent, so each must answer with a permanent redirect to it — one
 * hop, 308, query string intact — rather than a 404.
 */

const OLD_TO_NEW: [string, string][] = [
  ["/en", "/"],
  ["/ar", "/"],
  ["/en/search?q=ESP32", "/search?q=ESP32"],
  ["/ar/products/prod-1", "/products/prod-1"],
  ["/en/how-we-crawl", "/how-we-crawl"],
  ["/en/browse/electronics", "/trades/electronics"],
  ["/ar/browse/electronics/ics", "/trades/electronics/ics"],
  ["/browse/electronics", "/trades/electronics"],
  ["/en/suppliers/shop-a", "/shops/shop-a"],
  ["/suppliers/shop-a", "/shops/shop-a"],
  // The prefix goes first; the listing's own redirect is checked below.
  ["/en/listings/listing-1", "/listings/listing-1"],
  // A listing is one shop's offer; its page is now the product's.
  ["/listings/listing-1", "/products/prod-1"],
  ["/listings/off-2", "/products/prod-1"],
];

for (const [from, to] of OLD_TO_NEW) {
  test(`${from} → ${to}`, async ({ request }) => {
    const response = await request.get(from, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    const location = new URL(response.headers().location, "http://x");
    expect(`${location.pathname}${location.search}`).toBe(to);
  });
}

test("an old listing URL ends on its product page", async ({ page }) => {
  await page.goto("/en/listings/listing-1");
  expect(new URL(page.url()).pathname).toBe("/products/prod-1");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("ESP32-WROOM-32");
});

test("a listing that does not exist is a real 404", async ({ request }) => {
  const response = await request.get("/listings/does-not-exist", { maxRedirects: 0 });
  expect(response.status()).toBe(404);
});

test("a listing with no product has nowhere to go, so it is a 404 too", async ({ request }) => {
  const response = await request.get("/listings/listing-orphan", { maxRedirects: 0 });
  expect(response.status()).toBe(404);
});

test("current URLs are served, not redirected", async ({ request }) => {
  for (const path of ["/", "/search?q=ESP32", "/trades/electronics", "/shops/shop-a"]) {
    const response = await request.get(path, { maxRedirects: 0 });
    expect(response.status(), path).toBe(200);
  }
});

test("the document is English, with no language alternates", async ({ page }) => {
  await page.goto("/products/prod-1");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("link[hreflang]")).toHaveCount(0);
});
