import { expect, test, type Page } from "@playwright/test";

/**
 * Stale products are hidden by default, like out of stock (rule C2b): "stale"
 * is last checked more than 45 days ago, the same line as the "Price may be
 * out of date" warning (F2).
 *
 * Fixtures: "capacitor" in fixtures/search.mjs is 4 in stock and fresh, 4 in
 * stock and stale, 2 out of stock and fresh, 2 out of stock and stale;
 * "dusty" is only stale, "ancient" only stale and out of stock. The products
 * are in fixtures/product.mjs, the shops in fixtures/shops.mjs.
 */

const count = (page: Page) => page.locator("[data-count]");
const rows = (page: Page) => page.locator("[data-result=row]");

test.describe("results hide stale products by default (C2b)", () => {
  test("the toolbar says how many each default hides, and one click shows them", async ({
    page,
  }) => {
    await page.goto("/search?q=capacitor");
    await expect(count(page)).toHaveText("4 in stock · 2 more out of stock · 4 more out of date");
    await expect(rows(page)).toHaveCount(4);
    await expect(rows(page).filter({ hasText: "old" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Recently checked" })).toHaveAttribute(
      "aria-current",
      "true",
    );

    await page.getByRole("link", { name: "4 more out of date" }).click();
    await expect(page).toHaveURL(/stale=all/);
    // Each count is what its own click adds: the stale ones out of stock
    // were in neither, and now count as out of stock.
    await expect(count(page)).toHaveText("8 in stock · 4 more out of stock");
    await expect(rows(page).filter({ hasText: "old" }).first()).toBeVisible();
    await expect(rows(page).locator('[data-freshness="warn"]').first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Recently checked" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  test("showing out of stock first: the stale count then covers them too", async ({ page }) => {
    await page.goto("/search?q=capacitor");
    await page.getByRole("link", { name: "2 more out of stock" }).click();
    await expect(page).toHaveURL(/in_stock=all/);
    await expect(count(page)).toHaveText("6 results · 6 more out of date");

    await page.getByRole("link", { name: "6 more out of date" }).click();
    await expect(count(page)).toHaveText("12 results");
  });

  test("the chip toggles the filter, and the parameter with it", async ({ page }) => {
    await page.goto("/search?q=capacitor");
    await page.getByRole("link", { name: "Recently checked" }).click();
    await expect(page).toHaveURL(/stale=all/);
    await page.getByRole("link", { name: "Recently checked" }).click();
    await expect(page).not.toHaveURL(/stale=/);
    await expect(count(page)).toHaveText("4 in stock · 2 more out of stock · 4 more out of date");
  });

  test("works without JavaScript", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto("/search?q=capacitor");
    await page.getByRole("link", { name: "4 more out of date" }).click();
    await expect(page).toHaveURL(/stale=all/);
    await context.close();
  });

  test("when everything that matched is stale, the page says so and offers them", async ({
    page,
  }) => {
    await page.goto("/search?q=dusty");
    const state = page.locator('[data-state="only-stale"]');
    await expect(state).toContainText("Nothing checked recently");
    await expect(state).toContainText("3 products match, but none was checked in the last 45 days");
    await state.getByRole("link", { name: "Show 3 out of date" }).click();
    await expect(count(page)).toHaveText("3 in stock");
  });

  test("matches both out of stock and out of date get one way to everything", async ({
    page,
  }) => {
    await page.goto("/search?q=ancient");
    const state = page.locator('[data-state="only-hidden"]');
    await expect(state).toContainText("Nothing in stock and recently checked");
    await expect(state.getByRole("link")).toHaveCount(1);
    await state.getByRole("link", { name: "Show all 3" }).click();
    await expect(page).toHaveURL(/in_stock=all/);
    await expect(page).toHaveURL(/stale=all/);
    await expect(count(page)).toHaveText("3 results");
  });
});

test.describe("a product page folds stale offers (C2b)", () => {
  test("the stale offers fold under their own count, and the fresh one leads", async ({
    page,
  }) => {
    await page.goto("/products/p-stale-mix");
    const listed = page.locator("section[aria-labelledby=offers-heading] > div > ul [data-offer]");
    await expect(listed).toHaveCount(1);
    await expect(listed.first()).toHaveAttribute("data-offer", "o-sm-fresh");

    // Cheaper, and stale: folded, not leading the page.
    const folded = page.locator("[data-stale] [data-offer]");
    await expect(folded).toHaveCount(2);
    await expect(folded.first()).toBeHidden();
    await page.getByText("Show 2 out of date offers").click();
    await expect(folded.first()).toBeVisible();
    await expect(folded.first().locator('[data-freshness="warn"]')).toBeVisible();

    await expect(page.locator("[data-summary]")).toContainText("1 offer in stock at 1 shop");
    await expect(page.locator("[data-summary] [data-price]")).toHaveText("EGP 120");
    await expect(page.locator("[data-summary] [role=note]")).toHaveCount(0);
  });

  test("on a phone the bottom bar points at the fresh offer, not the cheaper stale one", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/products/p-stale-mix");
    const bar = page.locator("[data-bottom-bar]");
    await expect(bar.locator("[data-price]")).toHaveText("EGP 120");
    await expect(bar.getByRole("link", { name: "View at Nile Parts" })).toBeVisible();
  });

  test("a product whose every offer is stale still renders, and says so once", async ({
    page,
  }) => {
    const response = await page.goto("/products/p-all-stale");
    expect(response?.status()).toBe(200);
    await expect(page.locator("[data-offer]")).toHaveCount(2);
    await expect(page.locator("[data-stale]")).toHaveCount(0);
    await expect(page.locator("[data-summary] [role=note]")).toHaveText(
      "Price may be out of date. Last checked 76 days ago. Confirm it on the shop's page.",
    );
  });
});

test.describe("a shop's own page (C2b)", () => {
  test("a stale shop lists its products anyway, beside its stale note", async ({ page }) => {
    await page.goto("/shops/stale-shop");
    await expect(page.locator("[data-stale-note]")).toBeVisible();
    const products = page.locator("[data-shop-products]");
    await expect(products.locator("[data-result]")).toHaveCount(2);
    const chip = products.getByRole("link", { name: "Recently checked" });
    await expect(chip).not.toHaveAttribute("aria-current");

    // The chip still hides them, and the page says what it hid.
    await chip.click();
    await expect(page).toHaveURL(/\/shops\/stale-shop\?stale=hide$/);
    await expect(products.locator('[data-state="only-stale"]')).toBeVisible();
    await products.getByRole("link", { name: "Show 2 out of date" }).click();
    await expect(page).toHaveURL(/\/shops\/stale-shop$/);
    await expect(products.locator("[data-result]")).toHaveCount(2);
  });

  test("a fresh shop keeps the usual default", async ({ page }) => {
    await page.goto("/shops/shop-a");
    await expect(
      page.locator("[data-shop-products]").getByRole("link", { name: "Recently checked" }),
    ).toHaveAttribute("aria-current", "true");
  });
});
