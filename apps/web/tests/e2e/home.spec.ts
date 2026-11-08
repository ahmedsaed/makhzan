import { expect, test } from "@playwright/test";

/**
 * The home page, on a phone and on a desktop. Stub data: the trades fixture
 * (tests/e2e/fixtures/trades.mjs), the shops fixture and the stub's own
 * search, which answers `min_suppliers=2` with one product sold by 3 shops.
 */

const SECTIONS = ["hero", "trades", "several-shops", "shops", "for-suppliers"];

test.describe("on a phone", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("keeps the trade rows, each saying what is inside", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", {
        level: 1,
        name: "Find parts and materials across Egypt's suppliers.",
      }),
    ).toBeVisible();
    await expect(
      page.getByText("57,207 products from 8 shops. Prices rechecked about weekly."),
    ).toBeVisible();

    const rows = page.locator("[data-trade]");
    await expect(rows).toHaveCount(8);
    // Largest first, and the "Other" bucket never describes a trade.
    const first = rows.first();
    await expect(first).toBeVisible();
    await expect(first).toHaveAttribute("data-trade", "seals-bearings");
    await expect(first).toContainText("Seals & Bearings");
    await expect(first).toContainText("1,580");
    await expect(first).toContainText("O-Rings, bearings, oil seals, gaskets");
    await expect(first).not.toContainText("Other");
    // The desktop cards are not shown as well.
    await expect(page.locator("[data-home-trade]").first()).toBeHidden();

    await page.getByRole("link", { name: "All 11 trades" }).click();
    await expect(page).toHaveURL("/trades");
  });

  test("does not focus the search field, so the keyboard stays down", async ({ page }) => {
    await page.goto("/");
    const field = page.getByRole("searchbox", { name: "Search" });
    await expect(field).toBeVisible();
    expect(await field.evaluate((el) => el === document.activeElement)).toBe(false);
    // Revisiting the page is what brought the keyboard up.
    await page.getByRole("link", { name: "All 11 trades" }).click();
    await expect(page).toHaveURL("/trades");
    await page.goBack();
    await expect(field).toBeVisible();
    expect(await field.evaluate((el) => el === document.activeElement)).toBe(false);
    // A tap still focuses it.
    await field.click();
    expect(await field.evaluate((el) => el === document.activeElement)).toBe(true);
  });

  test("a trade row's categories wrap at 320px instead of being cut off", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    await page.goto("/");
    const phrase = page
      .locator("[data-trade=seals-bearings]")
      .getByText("O-Rings, bearings, oil seals, gaskets", { exact: true });
    await expect(phrase).toBeVisible();
    const box = await phrase.evaluate((el) => ({
      clipped: el.scrollWidth > el.clientWidth,
      ellipsis: getComputedStyle(el).textOverflow === "ellipsis",
      lines: Math.round(
        el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight),
      ),
    }));
    expect(box.clipped).toBe(false);
    expect(box.ellipsis).toBe(false);
    expect(box.lines).toBeGreaterThan(1);
  });

  test("has no horizontal scroll", async ({ page }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
});

test.describe("on a desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("every section spans the page, not a narrow strip", async ({ page }) => {
    await page.goto("/");
    for (const name of SECTIONS.filter((s) => s !== "hero")) {
      const box = await page.locator(`[data-home-section="${name}"]`).boundingBox();
      expect(box, name).not.toBeNull();
      expect(box!.width, name).toBeGreaterThan(1000);
    }
    // The hero shares its row with "How makhzan works"; together they fill it.
    const hero = await page.locator('[data-home-section="hero"]').boundingBox();
    const how = await page.locator('[data-home-section="how"]').boundingBox();
    expect(hero!.width + how!.width).toBeGreaterThan(1000);
    expect(Math.abs(hero!.y - how!.y)).toBeLessThan(80);
  });

  test("does not focus the search field until it is clicked", async ({ page }) => {
    await page.goto("/");
    const field = page.getByRole("searchbox", { name: "Search" });
    await expect(field).toBeVisible();
    expect(await field.evaluate((el) => el === document.activeElement)).toBe(false);
    await field.click();
    expect(await field.evaluate((el) => el === document.activeElement)).toBe(true);
  });

  test("shows the totals as figures and example searches", async ({ page }) => {
    await page.goto("/");
    const hero = page.locator('[data-home-section="hero"]');
    await expect(hero.getByRole("definition").filter({ hasText: "57,207" })).toBeVisible();
    await expect(hero.getByRole("term").filter({ hasText: "categories" })).toBeVisible();
    // The one-line version is for phones.
    await expect(hero.getByText("Prices rechecked about weekly.")).toBeHidden();
    const examples = page.getByRole("list", { name: "Example searches" });
    await expect(examples.getByRole("link", { name: "ESP32", exact: true })).toHaveAttribute(
      "href",
      "/search?q=ESP32",
    );
  });

  test("trades are cards whose biggest categories are links", async ({ page }) => {
    await page.goto("/");
    const cards = page.locator("[data-home-trade]");
    await expect(cards).toHaveCount(8);
    const first = cards.first();
    await expect(first).toHaveAttribute("data-home-trade", "seals-bearings");
    await expect(first.getByRole("link", { name: /^O-Rings/ })).toHaveAttribute(
      "href",
      "/trades/seals-bearings/o-rings",
    );
    await expect(first).not.toContainText("Other Seals");
    // The trades past eight are still one click away.
    await expect(page.getByText("Also:")).toBeVisible();
    await expect(page.getByRole("link", { name: "Cleaning" })).toHaveAttribute(
      "href",
      "/trades/cleaning",
    );
  });

  test("shows products sold by several shops, with their price range", async ({ page }) => {
    await page.goto("/");
    const strip = page.locator('[data-home-section="several-shops"]');
    await expect(strip.getByText("EGP 185 – 210")).toBeVisible();
    await expect(strip.getByText("3 shops")).toBeVisible();
    await expect(strip.getByRole("link").first()).toHaveAttribute("href", "/products/prod-1");
  });

  test("lists the shops with their freshness, and hides an empty one", async ({ page }) => {
    await page.goto("/");
    const shops = page.locator("[data-home-shop]");
    await expect(shops).toHaveCount(2);
    await expect(page.locator('[data-home-shop="stale-shop"]')).toHaveAttribute(
      "data-stale",
      "true",
    );
    await expect(page.locator('[data-home-shop="stale-shop"]')).toContainText(
      "Price may be out of date",
    );
    await expect(
      page.locator('[data-home-section="for-suppliers"]').getByRole("link", {
        name: "For suppliers",
      }),
    ).toHaveAttribute("href", "/for-suppliers");
  });

  test("renders every section without JavaScript", async ({ browser }) => {
    const context = await browser.newContext({
      javaScriptEnabled: false,
      viewport: { width: 1440, height: 900 },
    });
    const page = await context.newPage();
    await page.goto("/");
    for (const name of SECTIONS) {
      await expect(page.locator(`[data-home-section="${name}"]`), name).toBeVisible();
    }
    await context.close();
  });
});
