import { expect, test } from "@playwright/test";

/**
 * All trades, a trade and a category; home is in home.spec.ts. Stub data:
 * tests/e2e/fixtures/trades.mjs.
 */

// "Trade" names a profession, not a kind of product; the grouping is a
// "department" (November 2026). Nothing a visitor reads may still say trade —
// not the nav, the headings, the stat tiles or the page title.
for (const path of ["/", "/departments", "/departments/seals-bearings"]) {
  test(`no visible text on ${path} says "trade"`, async ({ page }) => {
    await page.goto(path);
    expect(await page.locator("body").innerText()).not.toMatch(/trade/i);
    expect(await page.title()).not.toMatch(/trade/i);
  });
}

test("all trades lists every trade by size", async ({ page }) => {
  await page.goto("/departments");
  await expect(page.getByRole("heading", { level: 1, name: "All 11 departments" })).toBeVisible();
  await expect(page.locator("[data-trade]")).toHaveCount(11);
  await expect(page.locator("[data-trade]").last()).toHaveAttribute("data-trade", "cleaning");
  await expect(page).toHaveTitle(/All departments/);
});

test("all trades is a directory across the whole width on a desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/departments");
  const directory = page.locator("ul:has(> [data-trade])");
  expect((await directory.boundingBox())?.width).toBeGreaterThan(1000);

  // The trade that holds most of the catalogue is mapped group by group.
  const seals = page.locator("[data-trade=seals-bearings]");
  await expect(seals).toHaveAttribute("data-major", "true");
  await expect(seals.locator("[data-group]")).toHaveCount(2);
  await expect(seals.getByRole("link", { name: /^Seals & Gaskets/ })).toHaveAttribute(
    "href",
    "/departments/seals-bearings/seals",
  );
  const oRings = seals.getByRole("link", { name: /^O-Rings/ });
  await expect(oRings).toBeVisible();
  await expect(oRings).toHaveText("O-Rings 400");
  await expect(oRings).toHaveAttribute("href", "/departments/seals-bearings/o-rings");
  // Biggest first, but the "Other" bucket last however big it is.
  await expect(seals.locator("[data-group='seals-bearings:seals'] li")).toHaveText([
    "O-Rings 400",
    "Oil Seals 250",
    "Gaskets 90",
    "Other Seals 500",
  ]);

  // A smaller trade lists its categories as links too, and is not folded away.
  const piping = page.locator("[data-trade=piping]");
  await expect(piping).not.toHaveAttribute("data-major", "true");
  await expect(piping.getByRole("link", { name: "Butterfly Valves 120" })).toHaveAttribute(
    "href",
    "/departments/piping/valves",
  );
  await expect(page.getByRole("button", { name: /^Categories in/ })).toHaveCount(0);
});

test("on a phone each trade is a row, its categories behind a chevron", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/departments");
  const seals = page.locator("[data-trade=seals-bearings]");
  await expect(seals.getByRole("link", { name: /Seals & Bearings/ })).toHaveAttribute(
    "href",
    "/departments/seals-bearings",
  );
  const phrase = seals.getByText("O-Rings, bearings, oil seals, gaskets", { exact: true });
  await expect(phrase).toBeVisible();
  // Wrapped, never cut off with an ellipsis.
  expect(
    await phrase.evaluate(
      (el) => el.scrollWidth <= el.clientWidth && getComputedStyle(el).textOverflow !== "ellipsis",
    ),
  ).toBe(true);
  const oRings = seals.getByRole("link", { name: "O-Rings 400" });
  await expect(oRings).toBeHidden();

  const toggle = seals.getByRole("button", { name: "Categories in Seals & Bearings" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect((await toggle.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(oRings).toBeVisible();
  // Rule S4: a link in the list is a full finger's height.
  expect((await oRings.boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await oRings.click();
  await expect(page).toHaveURL("/departments/seals-bearings/o-rings");
});

test("all trades does not scroll sideways at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/departments");
  await page.getByRole("button", { name: "Categories in Seals & Bearings" }).click();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

test("a trade page fills a wide screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/departments/seals-bearings");
  // The group tiles lie on their side across the page, not a strip of squares.
  const groups = page.getByRole("navigation", { name: "Groups" });
  expect((await groups.boundingBox())?.width).toBeGreaterThan(1000);
  const tile = await groups.getByRole("link").first().boundingBox();
  expect(tile!.width).toBeGreaterThan(tile!.height * 3);
  // The search sits beside the name rather than under it.
  const heading = await page.getByRole("heading", { level: 1 }).boundingBox();
  const search = await page
    .getByRole("searchbox", { name: "Search in Seals & Bearings" })
    .boundingBox();
  expect(Math.abs(heading!.y - search!.y)).toBeLessThan(40);
});

test("a trade page shows its groups, its biggest categories and results", async ({ page }) => {
  await page.goto("/departments/seals-bearings");
  await expect(page).toHaveTitle(/Seals & Bearings/);
  await expect(page.getByRole("heading", { level: 1, name: "Seals & Bearings" })).toBeVisible();

  // The empty Filtration group is not a tile: it would lead nowhere. On a
  // desktop a group tile also says how big it is and what is inside.
  const groups = page.getByRole("navigation", { name: "Groups" }).getByRole("link");
  await expect(groups).toHaveText([/^Seals & Gaskets/, /^Bearings & Transmission/]);
  await expect(groups.first()).toContainText("1,240");
  await expect(groups.first()).toContainText("O-Rings, oil seals, gaskets");
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
  await page.goto("/departments/seals-bearings?in_stock=false");
  await expect(page.locator("[data-result=row]")).toHaveCount(4);
});

test("a group page narrows to the products filed under its categories", async ({ page }) => {
  await page.goto("/departments/seals-bearings/seals?in_stock=all");
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
  await expect(page.locator("[data-result=row]")).toContainText([/O-Ring/, /Oil Seal/]);
  await expect(page.getByText(/Showing everything in/)).toHaveCount(0);

  await page.goto("/departments/seals-bearings/transmission?in_stock=all");
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
  await expect(page.locator("[data-result=row]").first()).toContainText("Ball Bearing");
});

test("the trade's filters list its own categories, and narrow in place", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/departments/seals-bearings?in_stock=all");
  const rail = page.getByRole("complementary", { name: "Filters" });
  await expect(rail.getByRole("radio")).toHaveCount(4);
  await expect(rail).toContainText("Bearings");
  await expect(rail).not.toContainText("Integrated Circuits");

  await rail.getByRole("radio", { name: /O-Rings/ }).check();
  await expect(page).toHaveURL(/\/departments\/seals-bearings\?.*category=seals-bearings%3Ao-rings/);
  await expect(page.locator("[data-result=row]")).toHaveCount(1);
  await page.getByRole("link", { name: "O-Rings ✕" }).click();
  await expect(page.locator("[data-result=row]")).toHaveCount(4);
});

test("a category from another trade is ignored, not shown under this one", async ({ page }) => {
  await page.goto("/departments/seals-bearings?category=electronics:ics");
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
});

test("bad parameters degrade instead of failing", async ({ page }) => {
  let response = await page.goto("/departments/seals-bearings?sort=title:asc&offset=-3&min_price=x");
  expect(response?.status()).toBe(200);
  await expect(page.locator("[data-result=row]")).toHaveCount(2);

  // The API caps min_suppliers at 50; the page clamps rather than errors.
  response = await page.goto("/departments/seals-bearings?min_suppliers=500");
  expect(response?.status()).toBe(200);
  await expect(page.getByText("Nothing matched")).toBeVisible();
  await expect(page.locator("[data-state=not-answering]")).toHaveCount(0);
  await page.getByRole("link", { name: "Remove “2+ shops”" }).click();
  await expect(page.locator("[data-result=row]")).toHaveCount(2);
});

test("an API failure is a message on the page, not an error page", async ({ page }) => {
  // The stub fails every search in Gaskets.
  const response = await page.goto("/departments/seals-bearings/gaskets");
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { level: 1, name: "Gaskets" })).toBeVisible();
  await expect(page.getByText("Search is not answering")).toBeVisible();
});

test("a taxonomy failure degrades too, rather than claiming a 404", async ({ page }) => {
  // The stub fails /categories for this trade.
  for (const path of ["/departments/catfail", "/departments/catfail/anything"]) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(200);
    await expect(page.getByText("The catalogue is not answering")).toBeVisible();
  }
});

test("search in a trade stays in the trade", async ({ page }) => {
  await page.goto("/departments/seals-bearings");
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
  await page.goto("/departments/seals-bearings");
  await page
    .getByRole("navigation", { name: "Groups" })
    .getByRole("link", { name: "Bearings & Transmission" })
    .click();
  await expect(page).toHaveURL("/departments/seals-bearings/transmission");
  await expect(page.getByRole("navigation", { name: "Categories" }).getByRole("link")).toHaveText([
    "Bearings 300",
    "Couplings 40",
  ]);

  await page
    .getByRole("navigation", { name: "Categories" })
    .getByRole("link", { name: /Bearings/ })
    .click();
  await expect(page).toHaveURL("/departments/seals-bearings/bearings");
  await expect(page.getByRole("heading", { level: 1, name: "Bearings" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(
    "Departments›Seals & Bearings›Bearings & Transmission›Bearings",
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
  await page.goto("/departments/seals-bearings/oil-seals");
  await expect(page.locator("[data-view=list] [data-result=row]")).toHaveCount(1);
  await page.getByRole("link", { name: "2+ shops" }).click();
  await expect(page).toHaveURL(/min_suppliers=2/);
  await expect(page.locator("[data-result=row]")).toHaveCount(1);
  await context.close();
});

test("an unknown category is a 404", async ({ page }) => {
  const response = await page.goto("/departments/seals-bearings/not-a-category");
  expect(response?.status()).toBe(404);
});

test("an unknown trade is a 404 on its category pages too", async ({ page }) => {
  const response = await page.goto("/departments/not-a-trade/bearings");
  expect(response?.status()).toBe(404);
});

test.describe("canonical URLs of results pages", () => {
  test("filters drop out, so a filtered view counts as the page", async ({ page }) => {
    await page.goto("/departments/seals-bearings?sort=price_asc&in_stock=all&min_price=50");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://makhzan.test/departments/seals-bearings",
    );
  });

  test("paging stays, so page 2 is its own page", async ({ page }) => {
    await page.goto("/departments/seals-bearings?sort=price_asc&offset=24");
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://makhzan.test/departments/seals-bearings?offset=24",
    );
  });
});
