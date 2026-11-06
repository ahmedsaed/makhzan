import { expect, test } from "@playwright/test";

/**
 * Home, all trades, a trade and a category. Stub data: tests/e2e/fixtures/trades.mjs.
 */

test("home lists the eight biggest trades, each saying what is inside", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Find parts and materials across Cairo's suppliers.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("57,207 products from 8 shops. Prices rechecked about weekly."),
  ).toBeVisible();

  const rows = page.locator("[data-trade]");
  await expect(rows).toHaveCount(8);
  // Largest first, and the "Other" bucket never describes a trade.
  const first = rows.first();
  await expect(first).toHaveAttribute("data-trade", "seals-bearings");
  await expect(first).toContainText("Seals & Bearings");
  await expect(first).toContainText("1,580");
  await expect(first).toContainText("O-Rings, bearings, oil seals, gaskets");
  await expect(first).not.toContainText("Other");

  await page.getByRole("link", { name: "All 11 trades" }).click();
  await expect(page).toHaveURL("/trades");
});

test("all trades lists every trade by size", async ({ page }) => {
  await page.goto("/trades");
  await expect(page.getByRole("heading", { level: 1, name: "All 11 trades" })).toBeVisible();
  await expect(page.locator("[data-trade]")).toHaveCount(11);
  await expect(page.locator("[data-trade]").last()).toHaveAttribute("data-trade", "cleaning");
  await expect(page).toHaveTitle(/All trades/);
});

test("a trade page shows its groups, its biggest categories and results", async ({ page }) => {
  await page.goto("/trades/seals-bearings");
  await expect(page).toHaveTitle(/Seals & Bearings/);
  await expect(page.getByRole("heading", { level: 1, name: "Seals & Bearings" })).toBeVisible();

  // The empty Filtration group is not a tile: it would lead nowhere.
  const groups = page.getByRole("navigation", { name: "Groups" }).getByRole("link");
  await expect(groups).toHaveText(["Seals & Gaskets", "Bearings & Transmission"]);
  await expect(page.getByRole("navigation", { name: "Categories" }).getByRole("link")).toHaveCount(
    6,
  );

  // In stock is on by default, and what it hides is counted and one click away.
  await expect(page.getByRole("link", { name: "In stock" })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
  await page.getByRole("link", { name: "2 more out of stock" }).click();
  await expect(page).toHaveURL(/in_stock=false/);
  await expect(page.locator("[data-result=row]")).toHaveCount(4);
  await expect(page.getByRole("link", { name: "In stock" })).not.toHaveAttribute("aria-current");
});

test("search in a trade stays in the trade", async ({ page }) => {
  await page.goto("/trades/seals-bearings");
  const field = page.getByRole("searchbox", {
    name: "Search in Seals & Bearings",
  });
  await field.fill("bearing");
  await field.press("Enter");
  await expect(page).toHaveURL(/\/search\?domain=seals-bearings&q=bearing/);
});

test("a category narrows the trade page", async ({ page }) => {
  await page.goto("/trades/seals-bearings");
  await page
    .getByRole("navigation", { name: "Groups" })
    .getByRole("link", { name: "Bearings & Transmission" })
    .click();
  await expect(page).toHaveURL("/trades/seals-bearings/transmission");
  await expect(page.getByRole("navigation", { name: "Categories" }).getByRole("link")).toHaveText([
    "Bearings 300",
    "Couplings 40",
  ]);

  await page
    .getByRole("navigation", { name: "Categories" })
    .getByRole("link", { name: /Bearings/ })
    .click();
  await expect(page).toHaveURL("/trades/seals-bearings/bearings");
  await expect(page.getByRole("heading", { level: 1, name: "Bearings" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(
    "Trades›Seals & Bearings›Bearings & Transmission›Bearings",
  );
  // Both bearings are out of stock: nothing shows, and the page says why.
  await expect(page.getByText("Nothing in stock here")).toBeVisible();
  await page.getByRole("link", { name: "2 more out of stock" }).click();
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
  await expect(page.locator("[data-result=row]").first()).toContainText("6204-2RS");
});

test("the trade page works with JavaScript off", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/trades/seals-bearings/oil-seals");
  await expect(page.locator("[data-view=list] [data-result=row]")).toHaveCount(1);
  await page.getByRole("link", { name: "2+ shops" }).click();
  await expect(page).toHaveURL(/min_suppliers=2/);
  await expect(page.locator("[data-result=row]")).toHaveCount(1);
  await context.close();
});

test("an unknown category is a 404", async ({ page }) => {
  const response = await page.goto("/trades/seals-bearings/not-a-category");
  expect(response?.status()).toBe(404);
});

test("an unknown trade is a 404 on its category pages too", async ({ page }) => {
  const response = await page.goto("/trades/not-a-trade/bearings");
  expect(response?.status()).toBe(404);
});
