import { expect, test } from "@playwright/test";

/**
 * The URL is the only state. Every narrowing is a link, so a filtered view can
 * be shared, bookmarked and reached with the back button — and none of it needs
 * JavaScript.
 */

test("search works with JavaScript disabled", async ({ browser }) => {
  // The header search is a plain GET form for exactly this reason.
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/en");
  await page.getByRole("searchbox").first().fill("ESP32");
  await page.getByRole("button", { name: "Search" }).first().click();
  await expect(page).toHaveURL(/\/en\/search\?q=ESP32/);
  await expect(page.getByRole("heading", { name: /ESP32-WROOM-32/ }).first()).toBeVisible();
  await context.close();
});

test("an identifier-shaped query explains why the order changed", async ({ page }) => {
  await page.goto("/en/search?q=ESP32");
  await expect(page.getByText(/ranked by identifier match first/)).toBeVisible();
});

test("a phrase gets no identifier band", async ({ page }) => {
  await page.goto("/en/search?q=digital%20caliper");
  await expect(page.getByText(/ranked by identifier match first/)).toHaveCount(0);
});

test("a facet narrows by navigation and can be undone", async ({ page }) => {
  await page.goto("/en/search?q=ESP32");
  await page.getByRole("link", { name: /Electronics/ }).first().click();
  await expect(page).toHaveURL(/domain=electronics/);

  // The active filter is visible as a chip, so the result count is explained.
  const chip = page.getByRole("link", { name: /electronics ✕/i }).first();
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page).not.toHaveURL(/domain=/);
});

test("empty results say so instead of showing an empty list", async ({ page }) => {
  await page.goto("/en/search?q=nothing");
  await expect(page.getByText("Nothing matched")).toBeVisible();
});

test("a category is addressed by domain and slug, never a bare slug", async ({ page }) => {
  await page.goto("/en/browse/electronics");
  await page.getByRole("link", { name: /Integrated Circuits/ }).first().click();
  await expect(page).toHaveURL("/en/browse/electronics/ics");
});

test("an unknown vertical is a 404, not an empty page", async ({ page }) => {
  const response = await page.goto("/en/browse/not-a-trade");
  expect(response?.status()).toBe(404);
});


test("the crawling policy is reachable and indexable in both languages", async ({ page }) => {
  // The page to point a supplier at. It must not depend on the API, and must
  // not be noindex — being findable is half its purpose.
  await page.goto("/en/how-we-crawl");
  await expect(page.getByRole("heading", { name: "How we collect this" })).toBeVisible();
  await expect(page.getByText(/robots\.txt/)).toBeVisible();
  await expect(page.locator('meta[name="robots"][content*="noindex"]')).toHaveCount(0);

  await page.goto("/ar/how-we-crawl");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "كيف نجمع هذه البيانات" })).toBeVisible();
});


test("the footer links to it", async ({ page }) => {
  await page.goto("/en");
  await expect(
    page.getByRole("link", { name: "How we collect this" }).first(),
  ).toHaveAttribute("href", "/en/how-we-crawl");
});
