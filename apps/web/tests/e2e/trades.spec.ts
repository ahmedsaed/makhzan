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
  // The header counts the catalogue; the toolbar says what is showing.
  await expect(page.locator("[data-catalogue-count]")).toHaveText("1,580 products");
  await expect(page.locator("[data-count]")).toHaveText("2 in stock · 2 more out of stock");
  await page.getByRole("link", { name: "2 more out of stock" }).click();
  await expect(page).toHaveURL(/in_stock=all/);
  await expect(page.locator("[data-result=row]")).toHaveCount(4);
  await expect(page.locator("[data-count]")).toHaveText("4 results");
  await expect(page.getByRole("link", { name: "In stock" })).not.toHaveAttribute("aria-current");
});

test("an old in_stock=false link still shows everything", async ({ page }) => {
  await page.goto("/trades/seals-bearings?in_stock=false");
  await expect(page.locator("[data-result=row]")).toHaveCount(4);
});

test("a group page narrows to the products filed under its categories", async ({ page }) => {
  await page.goto("/trades/seals-bearings/seals?in_stock=all");
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
  await expect(page.locator("[data-result=row]")).toContainText([/O-Ring/, /Oil Seal/]);
  await expect(page.getByText(/Showing everything in/)).toHaveCount(0);

  await page.goto("/trades/seals-bearings/transmission?in_stock=all");
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
  await expect(page.locator("[data-result=row]").first()).toContainText("Ball Bearing");
});

test("the trade's filters list its own categories, and narrow in place", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/trades/seals-bearings?in_stock=all");
  const rail = page.getByRole("complementary", { name: "Filters" });
  await expect(rail.getByRole("radio")).toHaveCount(4);
  await expect(rail).toContainText("Bearings");
  await expect(rail).not.toContainText("Integrated Circuits");

  await rail.getByRole("radio", { name: /O-Rings/ }).check();
  await expect(page).toHaveURL(/\/trades\/seals-bearings\?.*category=seals-bearings%3Ao-rings/);
  await expect(page.locator("[data-result=row]")).toHaveCount(1);
  await page.getByRole("link", { name: "O-Rings ✕" }).click();
  await expect(page.locator("[data-result=row]")).toHaveCount(4);
});

test("a category from another trade is ignored, not shown under this one", async ({ page }) => {
  await page.goto("/trades/seals-bearings?category=electronics:ics");
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
});

test("bad parameters degrade instead of failing", async ({ page }) => {
  let response = await page.goto("/trades/seals-bearings?sort=title:asc&offset=-3&min_price=x");
  expect(response?.status()).toBe(200);
  await expect(page.locator("[data-result=row]")).toHaveCount(2);

  // The API caps min_suppliers at 50; the page clamps rather than errors.
  response = await page.goto("/trades/seals-bearings?min_suppliers=500");
  expect(response?.status()).toBe(200);
  await expect(page.getByText("Nothing matched")).toBeVisible();
  await expect(page.locator("[data-state=not-answering]")).toHaveCount(0);
  await page.getByRole("link", { name: "Remove “2+ shops”" }).click();
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
});

test("an API failure is a message on the page, not an error page", async ({ page }) => {
  // The stub fails every search in Gaskets.
  const response = await page.goto("/trades/seals-bearings/gaskets");
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Gaskets" })).toBeVisible();
  await expect(page.getByText("Search is not answering")).toBeVisible();
});

test("a taxonomy failure degrades too, rather than claiming a 404", async ({ page }) => {
  // The stub fails /categories for this trade.
  for (const path of ["/trades/catfail", "/trades/catfail/anything"]) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(200);
    await expect(page.getByText("The catalogue is not answering")).toBeVisible();
  }
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

test("searching a trade for nothing says everything in it", async ({ page }) => {
  await page.goto("/search?domain=seals-bearings&q=");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Everything in Seals & Bearings",
  );
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
  await expect(page.getByText("Nothing in stock", { exact: true })).toBeVisible();
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
