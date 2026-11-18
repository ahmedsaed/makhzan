import { expect, test } from "@playwright/test";

/**
 * The category icon set on department pages (option 3 of the icon pilot,
 * docs/DESIGN.md "Category icons"): groups are tiles with object icons,
 * categories are chips with symbols, the "Biggest in" shortcuts are light pills
 * naming their group, and a department without a drawn set gets plain chips.
 * Stub data: the Electronics groups in tests/e2e/stub-api.mjs, Seals & Bearings
 * in tests/e2e/fixtures/departments.mjs.
 */

test("Electronics' group tiles each carry their own icon", async ({ page }) => {
  await page.goto("/departments/electronics");
  const groups = page.getByRole("navigation", { name: "Groups" });
  await expect(groups.getByRole("link")).toHaveCount(3);
  for (const ref of ["electronics:components", "electronics:tools", "electronics:other"]) {
    await expect(groups.locator(`svg[data-icon="${ref}"]`)).toHaveCount(1);
  }
});

test("the biggest categories are pills naming their group, not tiles", async ({ page }) => {
  await page.goto("/departments/electronics");
  await expect(page.getByRole("heading", { name: "Biggest in Electronics" })).toBeVisible();
  const shortcuts = page.getByRole("navigation", { name: "Categories" }).getByRole("link");
  await expect(shortcuts).toHaveText([
    "Integrated Circuits · Components 120",
    "Resistors · Components 80",
    "Measurement & Test · Tools & Equipment 6",
    "Soldering · Tools & Equipment 3",
  ]);
  // "Accessories" is the only category in "Accessories & Other", which has a
  // tile already: it is not repeated as a shortcut.
  await expect(shortcuts.filter({ hasText: "Accessories" })).toHaveCount(0);

  // Each carries its symbol, keyed by ref: electronics:measurement, not tools:measurement.
  const measurement = shortcuts.filter({ hasText: "Measurement" });
  await expect(measurement.locator('svg[data-icon="electronics:measurement"]')).toHaveCount(1);
  await expect(measurement).toHaveAttribute("href", "/departments/electronics/measurement");

  // A pill is lighter than a group tile: no frame, a single line.
  const box = await shortcuts.first().boundingBox();
  expect(box!.height).toBeLessThanOrEqual(34);
  await expect(shortcuts.first().locator(".bg-photo-frame")).toHaveCount(0);
});

test("a group's categories are chips with their symbols", async ({ page }) => {
  await page.goto("/departments/electronics/components");
  await expect(page.getByRole("heading", { name: "Components · 200" })).toBeVisible();
  const chips = page.getByRole("navigation", { name: "Categories" }).getByRole("link");
  await expect(chips).toHaveText(["Integrated Circuits 120", "Resistors 80"]);
  await expect(chips.first().locator('svg[data-icon="electronics:ics"]')).toHaveCount(1);
  await expect(chips.last().locator('svg[data-icon="electronics:resistors"]')).toHaveCount(1);

  await page.goto("/departments/electronics/resistors");
  const current = page
    .getByRole("navigation", { name: "Categories" })
    .getByRole("link", { name: "Resistors 80" });
  await expect(current).toHaveAttribute("aria-current", "page");
});

test("a group of one category still lists it on its own page", async ({ page }) => {
  await page.goto("/departments/electronics/other");
  await expect(page.getByRole("navigation", { name: "Categories" }).getByRole("link")).toHaveText([
    "Accessories 4",
  ]);
});

test("a department without drawn icons has plain chips and pills", async ({ page }) => {
  await page.goto("/departments/seals-bearings/seals");
  const chips = page.getByRole("navigation", { name: "Categories" }).getByRole("link");
  await expect(chips).toHaveCount(4);
  await expect(chips.locator("svg")).toHaveCount(0);
  // Its group tiles keep one sensible stand-in until the set is drawn.
  const groups = page.getByRole("navigation", { name: "Groups" });
  await expect(groups.locator("svg")).toHaveCount(2);
  await expect(groups.locator("svg[data-icon]")).toHaveCount(0);

  await page.goto("/departments/seals-bearings");
  const shortcuts = page.getByRole("navigation", { name: "Categories" }).getByRole("link");
  await expect(shortcuts.first()).toHaveText("Other Seals · Seals & Gaskets 500");
  await expect(shortcuts.locator("svg")).toHaveCount(0);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 320, height: 700 } });

  for (const path of ["/departments/electronics", "/departments/electronics/components"]) {
    test(`${path} wraps its chips rather than scrolling sideways`, async ({ page }) => {
      await page.goto(path);
      const nav = page.getByRole("navigation", { name: "Categories" });
      expect(await nav.evaluate((el) => getComputedStyle(el).flexWrap)).toBe("wrap");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
