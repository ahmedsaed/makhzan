import { expect, test } from "@playwright/test";

/**
 * The shop pages and the supplier page. Fixtures: tests/e2e/fixtures/shops.mjs
 * — "Shop A" checked days ago, "Stale Shop" months ago, "Gone Shop" with no
 * active listings.
 */

test("the shop list hides empty shops and marks stale ones", async ({ page }) => {
  await page.goto("/shops");
  await expect(page.getByRole("heading", { level: 1, name: "Shops" })).toBeVisible();
  await expect(page.getByText("Each is rechecked about weekly.")).toBeVisible();

  await expect(page.locator("[data-shop]")).toHaveCount(2);
  await expect(page.getByText("Gone Shop")).toHaveCount(0);

  const fresh = page.locator('[data-shop="shop-a"]');
  await expect(fresh).not.toHaveAttribute("data-stale");
  await expect(fresh).toContainText("120 products");
  await expect(fresh).toContainText("84 in stock");
  await expect(fresh).toContainText("Electronics, Tools and Chemicals");
  await expect(fresh.locator('[data-freshness="quiet"]')).toHaveText("checked 3 days ago");
  await expect(fresh.getByRole("link")).toHaveAttribute("href", "/shops/shop-a");

  const stale = page.locator('[data-shop="stale-shop"]');
  await expect(stale).toHaveAttribute("data-stale", "true");
  await expect(stale.locator('[data-freshness="warn"]')).toContainText("out of date");
});

test("a fresh shop page: stats, the way out, search and what it carries", async ({ page }) => {
  await page.goto("/shops/shop-a");
  await expect(page).toHaveTitle(/^Shop A · makhzan/);
  await expect(page.getByRole("heading", { level: 1, name: "Shop A" })).toBeVisible();
  await expect(page.getByText("Bab El Louk, Cairo")).toBeVisible();
  await expect(page.locator("[data-stale-note]")).toHaveCount(0);
  await expect(page.locator('[data-tier="warn"]')).toHaveCount(0);
  await expect(page.locator("dl")).toContainText("Last checked3 days ago");

  // The only link out, tagged (P4).
  const visit = page.getByRole("link", { name: "Visit shop-a.test" });
  await expect(visit).toHaveAttribute("href", "https://www.shop-a.test/?ref=makhzan");
  await expect(visit).toHaveAttribute("data-umami-event-shop", "shop-a");

  await expect(page.getByText("Electronics 100 · Tools 15 · Chemicals 5")).toBeVisible();
  await expect(page.getByRole("link", { name: "Measuring Tools" })).toHaveAttribute(
    "href",
    "/search?shop=shop-a&category=tools%3Ameasurement",
  );

  // In stock here: the listing with a product opens it; the orphan is left out.
  const results = page.locator("[data-result]");
  await expect(results).toHaveCount(1);
  await expect(results.getByRole("link")).toHaveAttribute("href", "/products/prod-1");

  await expect(
    page.getByRole("link", { name: "Own this shop? Add your details." }),
  ).toHaveAttribute("href", "/for-suppliers");
});

test("searching a shop submits to /search scoped to it, without JavaScript", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/shops/shop-a");
  const field = page.getByRole("searchbox", { name: "Search Shop A" });
  await field.fill("lm358");
  await field.press("Enter");
  await expect(page).toHaveURL(/\/search\?shop=shop-a&q=lm358$/);
  await context.close();
});

test("a stale shop says so in plain language (F3)", async ({ page }) => {
  await page.goto("/shops/stale-shop");
  await expect(page.locator('[data-tier="warn"]')).toContainText("80 days ago");
  await expect(page.locator("[data-stale-note]")).toHaveText(
    /^We can't reach this shop's site at the moment\. Its prices and stock are as of \d{1,2} [A-Z][a-z]{2}( \d{4})? and may have changed\.$/,
  );
});

test("an unknown shop is a 404", async ({ page }) => {
  const response = await page.goto("/shops/no-such-shop");
  expect(response?.status()).toBe(404);
});

test("for suppliers offers three requests, each an email to the crawler's address", async ({
  page,
}) => {
  await page.goto("/for-suppliers");
  const requests = page.locator("[data-request]");
  await expect(requests).toHaveCount(3);
  await expect(requests.first()).toHaveAttribute("data-request", "remove");
  await expect(requests.first()).toContainText("within 7 days");

  for (const [id, subject] of [
    ["remove", "Remove my shop from makhzan"],
    ["add", "Add my shop to makhzan"],
    ["correct", "Correct my shop's details on makhzan"],
  ]) {
    const href = await page
      .locator(`[data-request="${id}"] a[href^="mailto:"]`)
      .getAttribute("href");
    expect(href).not.toBeNull();
    const url = new URL(href!);
    expect(url.pathname).toBe("crawler@merope.dev");
    expect(url.searchParams.get("subject")).toBe(subject);
    expect(url.searchParams.get("body")).toContain("Shop name:");
  }

  await expect(page.getByRole("link", { name: "How we crawl, in full" })).toHaveAttribute(
    "href",
    "/how-we-crawl",
  );
});

test("the shop and supplier pages do not scroll sideways at 320px (S4)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  for (const path of [
    "/shops",
    "/shops/shop-a",
    "/shops/stale-shop",
    "/for-suppliers",
    "/how-we-crawl",
    "/no-such-page",
  ]) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("the 404 page helps onward", async ({ page }) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("searchbox")).toBeVisible();
  const browse = page.getByRole("navigation", { name: "Browse" });
  await expect(browse.getByRole("link", { name: "All trades" })).toHaveAttribute("href", "/trades");
  await expect(browse.getByRole("link", { name: "All shops" })).toHaveAttribute("href", "/shops");
});
