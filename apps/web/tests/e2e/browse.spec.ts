import { expect, test } from "@playwright/test";

/**
 * The URL is the only state. Every narrowing is a link, so a filtered view can
 * be shared, bookmarked and reached with the back button — and none of it needs
 * JavaScript.
 */

test("search works with JavaScript disabled", async ({ browser }) => {
  // The home search is a plain GET form for exactly this reason.
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/");
  await page.getByRole("searchbox").fill("ESP32");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page).toHaveURL(/\/search\?q=ESP32/);
  await expect(page.getByText("ESP32-WROOM-32 DevKit V1").first()).toBeVisible();
  await context.close();
});

test("results are server-rendered, not hydrated into place", async ({ browser }) => {
  // With JavaScript off nothing can fetch or render on the client, so whatever
  // is here came from the server.
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/search?q=ESP32");
  await expect(page.locator("[data-view=list] [data-result=row]")).toHaveCount(2);
  await expect(page.getByText("EGP 185 – 210")).toBeVisible();
  await context.close();
});

test("home leads with one search field; other pages carry it in the header", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("searchbox")).toHaveCount(1);
  await page.goto("/search?q=ESP32");
  // The header field holds the query being shown, ready to edit.
  await expect(page.getByRole("searchbox")).toHaveValue("ESP32");
});

test("an identifier-shaped query explains why the order changed", async ({ page }) => {
  await page.goto("/search?q=ESP32");
  await expect(page.getByText(/ranked by identifier match first/)).toBeVisible();
});

test("a phrase gets no identifier band", async ({ page }) => {
  await page.goto("/search?q=digital%20caliper");
  await expect(page.getByText(/ranked by identifier match first/)).toHaveCount(0);
});

test("a filter narrows by navigation and can be undone", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/search?q=ESP32");
  await page
    .getByRole("complementary", { name: "Filters" })
    .getByRole("radio", { name: /Integrated Circuits/ })
    .check();
  await expect(page).toHaveURL(/category=electronics%3Aics/);

  // The active filter is visible as a chip, so the result count is explained.
  const chip = page.getByRole("link", { name: /Integrated Circuits ✕/ });
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page).not.toHaveURL(/category=/);
});

test("a chip toggles its parameter on and off", async ({ page }) => {
  await page.goto("/search?q=ESP32");
  await page.getByRole("link", { name: "2+ shops" }).click();
  await expect(page).toHaveURL(/min_suppliers=2/);
  await expect(page.getByRole("link", { name: "2+ shops" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await page.getByRole("link", { name: "2+ shops" }).click();
  await expect(page).not.toHaveURL(/min_suppliers/);
});

test("the list/grid choice is remembered", async ({ page }) => {
  await page.goto("/search?q=ESP32");
  await expect(page.locator("[data-view=list]")).toBeVisible();
  await page.getByRole("button", { name: "Grid view" }).click();
  await expect(page.locator("[data-view=grid] [data-result=card]")).toHaveCount(2);

  await page.reload();
  await expect(page.locator("[data-view=grid]")).toBeVisible();
  await expect(page.getByRole("button", { name: "Grid view" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("on a phone the filters open as a sheet", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/search?q=ESP32");
  await expect(page.getByRole("complementary", { name: "Filters" })).toBeHidden();
  await page.locator("summary", { hasText: "Category, price" }).click();
  const sheet = page.getByRole("dialog", { name: "Category, price" });
  await expect(sheet.getByRole("radio", { name: /Integrated Circuits/ })).toBeVisible();
  await page.getByRole("button", { name: "Close filters" }).click();
  await expect(sheet).toBeHidden();
});

test("nothing scrolls sideways at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  for (const path of ["/", "/search?q=ESP32", "/products/prod-1", "/departments/electronics"]) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("empty results say so instead of showing an empty list", async ({ page }) => {
  await page.goto("/search?q=nothing");
  await expect(page.getByText("Nothing matched")).toBeVisible();
});

test("a category is addressed through its trade, never a bare slug", async ({ page }) => {
  await page.goto("/departments/electronics");
  await page
    .getByRole("navigation", { name: "Categories" })
    .getByRole("link", { name: /Integrated Circuits/ })
    .click();
  await expect(page).toHaveURL("/departments/electronics/ics");
});

test("an unknown trade is a 404, not an empty page", async ({ page }) => {
  const response = await page.goto("/departments/not-a-trade");
  expect(response?.status()).toBe(404);
});

test("the crawling policy is reachable and indexable", async ({ page }) => {
  // The page to point a supplier at. It must not depend on the API, and must
  // not be noindex — being findable is half its purpose.
  await page.goto("/how-we-crawl");
  await expect(page.getByRole("heading", { level: 1, name: "How we crawl" })).toBeVisible();
  await expect(page.getByText(/robots\.txt/)).toBeVisible();
  await expect(page.getByRole("link", { name: "crawler@merope.dev" })).toHaveAttribute(
    "href",
    "mailto:crawler@merope.dev",
  );
  await expect(page.locator('meta[name="robots"][content*="noindex"]')).toHaveCount(0);
});

test("the footer links to the supplier pages", async ({ page }) => {
  await page.goto("/");
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "How we crawl" })).toHaveAttribute(
    "href",
    "/how-we-crawl",
  );
  await expect(footer.getByRole("link", { name: "For suppliers" })).toHaveAttribute(
    "href",
    "/for-suppliers",
  );
});

test("the footer theme control overrides the device", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.getByRole("button", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Device" }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("the theme follows the device by default", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await expect(page.locator("html")).toHaveClass(/dark/);
});
