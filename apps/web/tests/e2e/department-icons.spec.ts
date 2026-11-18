import { expect, test, type Locator, type Page } from "@playwright/test";

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
  await expect(groups.getByRole("link")).toHaveCount(6);
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

/** Whether every link in a row sits on one line. */
async function oneLine(row: Locator): Promise<boolean> {
  return row.evaluate((el) => {
    const tops = [...el.querySelectorAll("a")].map((a) =>
      Math.round(a.getBoundingClientRect().top),
    );
    return tops.length > 1 && new Set(tops).size === 1;
  });
}

/** Whether a link is wholly inside its row's visible part. */
async function inView(link: Locator): Promise<boolean> {
  return link.evaluate((el) => {
    const row = el.closest("[data-scroll-row]")!.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    return box.left >= row.left - 1 && box.right <= row.right + 1;
  });
}

async function noPageOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

// The owner's decision of 2026-11-18: on a phone the group tiles and the
// category chips are each one row scrolling sideways, so products start high.
test.describe("on a phone, groups and categories are sideways rows", () => {
  test.use({ viewport: { width: 320, height: 700 } });

  for (const path of [
    "/departments/electronics",
    "/departments/electronics/components",
    "/departments/seals-bearings/seals",
  ]) {
    test(`${path}: one row each, and the page does not scroll sideways`, async ({ page }) => {
      await page.goto(path);
      const groups = page.getByRole("navigation", { name: "Groups" });
      const categories = page.getByRole("navigation", { name: "Categories" });
      expect(await oneLine(groups)).toBe(true);
      expect(await oneLine(categories)).toBe(true);
      await noPageOverflow(page);
    });
  }

  test("the selected group and category are scrolled into view", async ({ page }) => {
    await page.goto("/departments/electronics/prototyping-supplies");
    const groups = page.getByRole("navigation", { name: "Groups" });
    // The smallest group is the last tile, off the right edge until scrolled to.
    await expect(groups.getByRole("link").last()).toHaveAttribute("aria-current", "true");
    await expect.poll(() => inView(groups.getByRole("link").last())).toBe(true);
    // The page itself did not move to show it.
    expect(await page.evaluate(() => window.scrollY)).toBe(0);

    await page.goto("/departments/electronics/resistors");
    const chip = page
      .getByRole("navigation", { name: "Categories" })
      .getByRole("link", { name: "Resistors 80" });
    await expect.poll(() => inView(chip)).toBe(true);
  });

  test("an edge fades only while it hides content", async ({ page }) => {
    await page.goto("/departments/electronics");
    const row = page.getByRole("navigation", { name: "Categories" });
    const mask = () => row.evaluate((el) => getComputedStyle(el).maskImage);

    // At the start: more to the right only, so only the right edge fades.
    await expect(row).toHaveAttribute("data-more-end", "true");
    await expect(row).not.toHaveAttribute("data-more-start");
    expect(await mask()).toMatch(/^linear-gradient\((to right|90deg)/);

    // In the middle: both edges.
    await row.evaluate((el) => {
      el.style.scrollBehavior = "auto";
      el.scrollLeft = (el.scrollWidth - el.clientWidth) / 2;
    });
    await expect(row).toHaveAttribute("data-more-start", "true");
    await expect(row).toHaveAttribute("data-more-end", "true");
    expect(await mask()).toMatch(
      /^linear-gradient\((to right|90deg), (transparent|rgba\(0, 0, 0, 0\))/,
    );

    // At the end: the right edge is sharp again, the left one fades.
    await row.evaluate((el) => (el.scrollLeft = el.scrollWidth));
    await expect(row).not.toHaveAttribute("data-more-end");
    await expect(row).toHaveAttribute("data-more-start", "true");
    expect(await mask()).toMatch(/^linear-gradient\((to left|270deg)/);
  });

  test("there are no chevron buttons, only the links", async ({ page }) => {
    // The owner, 2026-11-18: the fade and the partly shown next item are the cues.
    await page.goto("/departments/electronics");
    for (const name of ["Groups", "Categories"]) {
      const row = page.getByRole("navigation", { name });
      await expect(row.locator("button")).toHaveCount(0);
      // Nor beside the row, where an edge control would sit.
      const besideButtons = await row.evaluate(
        (el) =>
          [...el.parentElement!.children].filter((c) => c !== el && c.matches("button")).length,
      );
      expect(besideButtons).toBe(0);
    }
  });

  test("the next item shows partly, as the hint that the row goes on", async ({ page }) => {
    await page.goto("/departments/electronics/components");
    const cut = await page.getByRole("navigation", { name: "Categories" }).evaluate((el) => {
      const right = el.getBoundingClientRect().right;
      return [...el.querySelectorAll("a")].some((a) => {
        const box = a.getBoundingClientRect();
        return box.left < right - 8 && box.right > right;
      });
    });
    expect(cut).toBe(true);
  });

  test("a row that fits does not fade", async ({ page }) => {
    await page.goto("/departments/seals-bearings");
    const groups = page.getByRole("navigation", { name: "Groups" });
    await expect(groups).not.toHaveAttribute("data-more-end");
    await expect(groups).not.toHaveAttribute("data-more-start");
    expect(await groups.evaluate((el) => getComputedStyle(el).maskImage)).toBe("none");
  });

  test("keyboard focus brings a link into view", async ({ page }) => {
    await page.goto("/departments/electronics");
    const last = page.getByRole("navigation", { name: "Categories" }).getByRole("link").last();
    expect(await inView(last)).toBe(false);
    await last.focus();
    await expect.poll(() => inView(last)).toBe(true);
  });

  test("with reduced motion, nothing scrolls smoothly", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/departments/electronics");
    const row = page.getByRole("navigation", { name: "Categories" });
    expect(await row.evaluate((el) => getComputedStyle(el).scrollBehavior)).toBe("auto");
    // Focus scrolls the row at once rather than gliding.
    await row.getByRole("link").last().focus();
    expect(await row.evaluate((el) => el.scrollLeft)).toBeGreaterThan(100);
  });
});

test("from a tablet up, the rows wrap as before", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await page.goto("/departments/electronics");
  const row = page.getByRole("navigation", { name: "Categories" });
  expect(await row.evaluate((el) => getComputedStyle(el).flexWrap)).toBe("wrap");
  expect(await row.evaluate((el) => getComputedStyle(el).overflowX)).toBe("visible");
  expect(await row.evaluate((el) => getComputedStyle(el).maskImage)).toBe("none");
  const groups = page.getByRole("navigation", { name: "Groups" });
  expect(await groups.evaluate((el) => getComputedStyle(el).display)).toBe("grid");
});
