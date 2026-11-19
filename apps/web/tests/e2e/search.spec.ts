import { expect, test, type Page } from "@playwright/test";

/**
 * The results page against fixtures/search.mjs: "relay" is 30 products in
 * stock (exactly one page) and 6 out of stock, "obsolete" is only out of stock.
 */

const rows = (page: Page) => page.locator("[data-result=row]");
const count = (page: Page) => page.locator("[data-count]");

test("out of stock is hidden by default, and the page says how many (C2)", async ({ page }) => {
  await page.goto("/search?q=relay");
  await expect(count(page)).toHaveText("30 in stock · 6 more out of stock");
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
  await expect(count(page)).toHaveText("8 in stock · 1 more out of stock");

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

  // A category is a link: one tap picks it, as in the browse sheet.
  await page.locator("summary", { hasText: "Category, price" }).click();
  let sheet = page.getByRole("dialog", { name: "Category, price" });
  await expect(sheet.getByText("Electronics", { exact: true })).toBeVisible();
  await sheet.getByRole("link", { name: /Integrated Circuits/ }).click();
  await expect(page).toHaveURL(/category=electronics%3Aics/);

  // The price is a form, and keeps the category and the chips it does not own.
  await page.locator("summary", { hasText: "Category, price" }).click();
  sheet = page.getByRole("dialog", { name: "Category, price" });
  await expect(sheet.getByRole("link", { name: /Integrated Circuits/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await sheet.getByRole("spinbutton", { name: "Max" }).fill("300");
  await sheet.getByRole("button", { name: "Show results" }).click();

  await expect(page).toHaveURL(/category=electronics%3Aics/);
  await expect(page).toHaveURL(/max_price=300/);
  await expect(page).toHaveURL(/min_suppliers=2/);
  await expect(page.getByRole("link", { name: "Up to EGP 300 ✕" })).toBeVisible();
  await context.close();
});

test("on a phone, a category tapped in the sheet closes it and narrows the results", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/search?q=relay");
  await page.locator("summary", { hasText: "Category, price" }).click();
  const sheet = page.getByRole("dialog", { name: "Category, price" });
  await expect(sheet).toBeVisible();
  await sheet.getByRole("link", { name: /Measuring Tools/ }).click();
  await expect(page).toHaveURL(/category=tools%3Ameasurement/);
  await expect(sheet).toBeHidden();
  await expect(
    page.locator("details:has(> summary:has-text('Category, price'))"),
  ).not.toHaveAttribute("open");
  // 0, 5 … 25 are measuring tools and in stock.
  await expect(count(page)).toHaveText(/^6 in stock/);
  await expect(page.getByRole("link", { name: "Measuring Tools ✕" })).toBeVisible();
});

test("on desktop, the rail picks a category the moment it is clicked", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/search?q=relay&offset=30&in_stock=all");
  const rail = page.getByRole("complementary", { name: "Filters" });
  const categories = rail.getByRole("navigation", { name: "Category" });
  await expect(categories.getByRole("link", { name: /Any category/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await categories.getByRole("link", { name: /Measuring Tools/ }).click();
  await expect(page).toHaveURL(/category=tools%3Ameasurement/);
  // A new pick starts at the first page and keeps the other filters.
  await expect(page).not.toHaveURL(/offset=/);
  await expect(page).toHaveURL(/in_stock=all/);
  // Every category stays pickable once one is picked; only the pick is current.
  await expect(categories.getByRole("link", { name: /Resistors/ })).toBeVisible();
  await expect(categories.getByRole("link", { name: /Measuring Tools/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(categories.locator("[aria-current]")).toHaveCount(1);
  await expect(categories.getByRole("link", { name: /Measuring Tools/ })).toHaveCSS(
    "outline-style",
    "solid",
  );

  // "Any category" clears it, from the keyboard too.
  await categories.getByRole("link", { name: /Any category/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page).not.toHaveURL(/category=/);
});

test("the rail's price applies with the category kept, and Clear clears only the price", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/search?q=relay&category=electronics%3Aresistors");
  const price = page.getByRole("complementary", { name: "Filters" }).getByRole("form", {
    name: "Price",
  });
  await price.getByRole("spinbutton", { name: "Min" }).fill("100");
  await price.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/min_price=100/);
  await expect(page).toHaveURL(/category=electronics%3Aresistors/);
  await page
    .getByRole("complementary", { name: "Filters" })
    .getByRole("link", { name: "Clear" })
    .click();
  await expect(page).not.toHaveURL(/min_price/);
  await expect(page).toHaveURL(/category=electronics%3Aresistors/);
});

test("the rail looks like the browse sidebar: icons, 36px rows, a bordered panel", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/search?q=relay");
  const categories = page
    .getByRole("complementary", { name: "Filters" })
    .getByRole("navigation", { name: "Category" });
  await expect(categories.locator("[data-icon='electronics:resistors']")).toBeVisible();
  await expect(categories.locator("[data-department-icon=electronics]")).toBeVisible();
  const row = categories.getByRole("link", { name: /Measuring Tools/ });
  expect((await row.boundingBox())!.height).toBeGreaterThanOrEqual(36);
  await expect(categories.locator("div.rounded-card.border")).toHaveCount(1);
  // The same width as the department pages' sidebar from `lg` (17.5rem).
  const rail = page.getByRole("complementary", { name: "Filters" });
  expect(Math.round((await rail.boundingBox())!.width)).toBe(280);
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
  await expect(page.locator("[data-result=card]")).toHaveCount(30);
  const grid = await facts("[data-result=card]");
  expect(list).toHaveLength(30);
  expect(grid).toEqual(list);
  for (const fact of list) {
    expect(fact.price && fact.shops && fact.checked && fact.title).toBeTruthy();
  }
});

test("pages forward and back by offset", async ({ page }) => {
  // 36 with out of stock shown: a page of 30, then 6.
  await page.goto("/search?q=relay&in_stock=all");
  await expect(rows(page)).toHaveCount(30);
  await expect(page.getByText("1–30 of 36")).toBeVisible();
  await page.getByRole("link", { name: "Next" }).click();
  await expect(page).toHaveURL(/offset=30/);
  await expect(rows(page)).toHaveCount(6);
  await expect(page.getByText("31–36 of 36")).toBeVisible();
  await page.getByRole("link", { name: "Previous" }).click();
  await expect(page).not.toHaveURL(/offset/);
});

test("a search within a shop says so and can be widened", async ({ page }) => {
  await page.goto("/search?q=relay&shop=shop-a");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Results for “relay” in Shop A");
  // 0, 3, 4, 6, 8, 9, 12 … — every product Shop A sells, alone or with others.
  await expect(count(page)).toContainText("15 in stock");
  await page.getByRole("link", { name: "Search all shops" }).click();
  await expect(page).toHaveURL("/search?q=relay");
});

test("no results suggests dropping the filters that caused it", async ({ page }) => {
  await page.goto("/search?q=relay&min_price=5000");
  await expect(page.getByText("Nothing matched")).toBeVisible();
  await page.getByRole("link", { name: "Any price" }).click();
  await expect(page).toHaveURL("/search?q=relay");
  await expect(rows(page)).toHaveCount(30);
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

test("an empty query prompts and offers departments", async ({ page }) => {
  await page.goto("/search");
  await expect(page.getByRole("heading", { level: 1, name: "Search the catalogue" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Electronics/ })).toHaveAttribute(
    "href",
    "/departments/electronics",
  );
});

test("the title names the query", async ({ page }) => {
  await page.goto("/search?q=relay");
  await expect(page).toHaveTitle("relay · makhzan");
});

/**
 * A full page ends on a complete row: the grid's columns divide the page size
 * (tests/result-grid.test.tsx holds the classes to it; this checks the layout
 * the browser actually makes of them, on search and on a category page).
 */
for (const [name, url] of [
  ["search", "/search?q=relay"],
  ["a category page", "/departments/piping/valves"],
] as const) {
  for (const width of [390, 700, 1100, 1440]) {
    test(`on ${name} at ${width}px, a full page's last grid row is complete`, async ({ page }) => {
      await page.addInitScript(() => window.localStorage.setItem("makhzan:view", "grid"));
      await page.setViewportSize({ width, height: 900 });
      await page.goto(url);
      const cards = page.locator("[data-result=card]");
      await expect(cards).toHaveCount(30);
      const tops = await cards.evaluateAll((items) =>
        items.map((item) => Math.round(item.getBoundingClientRect().top)),
      );
      const rowsOf = new Map<number, number>();
      for (const top of tops) rowsOf.set(top, (rowsOf.get(top) ?? 0) + 1);
      const perRow = [...rowsOf.values()];
      expect(perRow[0]).toBeGreaterThan(1);
      expect(new Set(perRow), `cards per row: ${perRow.join(", ")}`).toEqual(new Set([perRow[0]]));
    });
  }
}
