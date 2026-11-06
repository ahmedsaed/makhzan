import { expect, test, type Page } from "@playwright/test";

/**
 * The results page against fixtures/search.mjs: "relay" is 30 products in
 * stock and 6 out of stock, "obsolete" is only out of stock.
 */

const rows = (page: Page) => page.locator("[data-result=row]");
const count = (page: Page) => page.locator("[data-count]");

test("out of stock is hidden by default, and the page says how many (C2)", async ({ page }) => {
  await page.goto("/search?q=relay");
  await expect(count(page)).toHaveText("30 results · 6 more out of stock");
  await expect(page.getByRole("link", { name: "In stock" })).toHaveAttribute(
    "aria-current",
    "true",
  );

  await page.getByRole("link", { name: "6 more out of stock" }).click();
  await expect(page).toHaveURL(/in_stock=all/);
  await expect(count(page)).toHaveText("36 results");
  await expect(page.getByRole("link", { name: "In stock" })).not.toHaveAttribute("aria-current");
});

test("the chips toggle and combine", async ({ page }) => {
  await page.goto("/search?q=relay");
  await page.getByRole("link", { name: "2+ shops" }).click();
  await expect(page).toHaveURL(/min_suppliers=2/);
  // 0, 4, 8 … 28 in stock; 32 is out of stock.
  await expect(count(page)).toHaveText("8 results · 1 more out of stock");

  await page.getByRole("link", { name: "In stock" }).click();
  await expect(page).toHaveURL(/min_suppliers=2.*in_stock=all|in_stock=all.*min_suppliers=2/);
  await expect(count(page)).toHaveText("9 results");

  await page.getByRole("link", { name: "In stock" }).click();
  await expect(page).not.toHaveURL(/in_stock/);
});

test("top categories for the query narrow the search", async ({ page }) => {
  await page.goto("/search?q=relay");
  const top = page.getByRole("region", { name: /Top categories for “relay”/ });
  await expect(top.getByRole("link")).toHaveCount(3);
  await top.getByRole("link", { name: /Resistors/ }).click();
  await expect(page).toHaveURL(/\/search\?q=relay&category=electronics%3Aresistors/);
  await expect(page.getByRole("link", { name: "Resistors ✕" })).toBeVisible();
});

test("on a phone, the filter sheet works without JavaScript", async ({ browser }) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  await page.goto("/search?q=relay&min_suppliers=2");
  await expect(page.getByRole("complementary", { name: "Filters" })).toBeHidden();

  await page.locator("summary", { hasText: "Category, price" }).click();
  const sheet = page.getByRole("dialog", { name: "Category, price" });
  await expect(sheet.getByText("Electronics", { exact: true })).toBeVisible();
  await sheet.getByRole("radio", { name: /Integrated Circuits/ }).check();
  await sheet.getByRole("spinbutton", { name: "Max" }).fill("300");
  await sheet.getByRole("button", { name: "Show results" }).click();

  await expect(page).toHaveURL(/category=electronics%3Aics/);
  await expect(page).toHaveURL(/max_price=300/);
  // The chip the sheet did not own survives the round trip.
  await expect(page).toHaveURL(/min_suppliers=2/);
  await expect(page.getByRole("link", { name: "Up to EGP 300 ✕" })).toBeVisible();
  await context.close();
});

test("on desktop, the rail picks a category the moment it is clicked", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/search?q=relay");
  const rail = page.getByRole("complementary", { name: "Filters" });
  await rail.getByRole("radio", { name: /Measuring Tools/ }).check();
  await expect(page).toHaveURL(/category=tools%3Ameasurement/);
  // Every category stays pickable once one is picked.
  await expect(rail.getByRole("radio", { name: /Resistors/ })).toBeVisible();
  await expect(rail.getByRole("radio", { name: /Measuring Tools/ })).toBeChecked();
});

test("sort works without JavaScript", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/search?q=relay&min_suppliers=2");
  await page.getByRole("combobox", { name: "Sort" }).selectOption("price:asc");
  await page.getByRole("button", { name: "Sort" }).click();
  await expect(page).toHaveURL(/sort=price%3Aasc/);
  await expect(page).toHaveURL(/min_suppliers=2/);
  await expect(rows(page).first()).toContainText("Relay module 0 channel");
  await context.close();
});

test("sort navigates on change with JavaScript", async ({ page }) => {
  await page.goto("/search?q=relay");
  await page.getByRole("combobox", { name: "Sort" }).selectOption("price:asc");
  await expect(page).toHaveURL(/sort=price%3Aasc/);
  await page.getByRole("combobox", { name: "Sort" }).selectOption("");
  await expect(page).not.toHaveURL(/sort=/);
});

test("list and grid carry the same facts (C1)", async ({ page }) => {
  await page.goto("/search?q=relay");
  const facts = async (selector: string) =>
    page.locator(selector).evaluateAll((items) =>
      items.map((item) => {
        const text = (item as HTMLElement).innerText;
        return {
          price: item.querySelector("[data-price]")?.textContent,
          shops: /\d shops|Shop [AC]/.exec(text)?.[0],
          checked: item.querySelector("[data-freshness]")?.textContent,
          title: /Relay module \d+ channel \d+V/.exec(text)?.[0],
        };
      }),
    );
  const list = await facts("[data-result=row]");
  await page.getByRole("button", { name: "Grid view" }).click();
  await expect(page.locator("[data-result=card]")).toHaveCount(24);
  const grid = await facts("[data-result=card]");
  expect(list).toHaveLength(24);
  expect(grid).toEqual(list);
  for (const fact of list) {
    expect(fact.price && fact.shops && fact.checked && fact.title).toBeTruthy();
  }
});

test("pages forward and back by offset", async ({ page }) => {
  await page.goto("/search?q=relay");
  await expect(rows(page)).toHaveCount(24);
  await page.getByRole("link", { name: "Next" }).click();
  await expect(page).toHaveURL(/offset=24/);
  await expect(rows(page)).toHaveCount(6);
  await expect(page.getByText("25–30 of 30")).toBeVisible();
  await page.getByRole("link", { name: "Previous" }).click();
  await expect(page).not.toHaveURL(/offset/);
});

test("a search within a shop says so and can be widened", async ({ page }) => {
  await page.goto("/search?q=relay&shop=shop-a");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Results for “relay” in Shop A");
  // 0, 3, 4, 6, 8, 9, 12 … — every product Shop A sells, alone or with others.
  await expect(count(page)).toContainText("15 results");
  await page.getByRole("link", { name: "Search all shops" }).click();
  await expect(page).toHaveURL("/search?q=relay");
});

test("no results suggests dropping the filters that caused it", async ({ page }) => {
  await page.goto("/search?q=relay&min_price=5000");
  await expect(page.getByText("Nothing matched")).toBeVisible();
  await page.getByRole("link", { name: "Any price" }).click();
  await expect(page).toHaveURL("/search?q=relay");
  await expect(rows(page)).toHaveCount(24);
});

test("only out-of-stock matches say so and offer to show them", async ({ page }) => {
  await page.goto("/search?q=obsolete");
  await expect(page.getByText("Nothing in stock")).toBeVisible();
  await page.getByRole("link", { name: "Show 2 out of stock" }).click();
  await expect(rows(page)).toHaveCount(2);
});

test("an API failure is a plain message, not a crash", async ({ page }) => {
  const response = await page.goto("/search?q=searchfail");
  expect(response?.status()).toBe(200);
  await expect(page.getByText("Search is not answering")).toBeVisible();
});

test("an empty query prompts and offers trades", async ({ page }) => {
  await page.goto("/search");
  await expect(page.getByRole("heading", { level: 1, name: "Search the catalogue" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Electronics/ })).toHaveAttribute(
    "href",
    "/trades/electronics",
  );
});

test("the title names the query", async ({ page }) => {
  await page.goto("/search?q=relay");
  await expect(page).toHaveTitle("relay · makhzan");
});
