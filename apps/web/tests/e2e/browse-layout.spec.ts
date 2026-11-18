import { expect, test, type Page } from "@playwright/test";

/**
 * Layout B on the department, group and category pages (docs/DESIGN.md,
 * "Department and category"; the owner's choice of 18 November 2026): the
 * department's tree as a sticky sidebar from `md`; on a phone no category row
 * at all, but a floating "{place} · Browse" pill that opens the tree as a
 * bottom sheet. Stub data: the Electronics groups in tests/e2e/stub-api.mjs,
 * Seals & Bearings in tests/e2e/fixtures/departments.mjs.
 */

const sidebar = (page: Page, department = "Electronics") =>
  page.getByRole("complementary").getByRole("navigation", { name: `Browse ${department}` });

async function noPageOverflow(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("the sidebar, from a tablet up", () => {
  test.use({ viewport: { width: 1280, height: 900 } });

  test("lists the groups with their icons and counts, collapsed on the department page", async ({
    page,
  }) => {
    await page.goto("/departments/electronics");
    const tree = sidebar(page);
    await expect(tree.getByRole("link", { name: /^All of Electronics/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const groups = tree.locator("[data-tree-group]");
    await expect(groups).toHaveCount(6);
    await expect(groups.first()).toHaveText(/^Components\s*200$/);
    for (const ref of ["electronics:components", "electronics:tools", "electronics:power"]) {
      await expect(tree.locator(`svg[data-icon="${ref}"]`)).toHaveCount(1);
    }
    // No category shows until its group is opened.
    await expect(tree.locator("[data-tree-category]").first()).toBeHidden();
  });

  test("expands a group in place, its categories with their symbols and counts", async ({
    page,
  }) => {
    await page.goto("/departments/electronics");
    const tree = sidebar(page);
    const toggle = tree.locator("[data-tree-node='electronics:components'] button");
    await expect(toggle).toHaveAccessibleName("Show categories in Components");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveAccessibleName("Hide categories in Components");
    const ics = tree.locator("[data-tree-category='electronics:ics']");
    await expect(ics).toBeVisible();
    await expect(ics).toHaveText(/^Integrated Circuits\s*120$/);
    await expect(ics.locator('svg[data-icon="electronics:ics"]')).toHaveCount(1);
    await expect(ics).toHaveAttribute("href", "/departments/electronics/ics");
  });

  test("on a category page, expands its group and outlines the category", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const tree = sidebar(page);
    const here = tree.locator("[data-tree-category='electronics:resistors']");
    await expect(here).toBeVisible();
    await expect(here).toHaveAttribute("aria-current", "page");
    const style = await here.evaluate((el) => {
      const s = getComputedStyle(el);
      return { outline: s.outlineStyle, weight: s.fontWeight, fill: s.backgroundColor };
    });
    expect(style.outline).toBe("solid");
    expect(Number(style.weight)).toBeGreaterThanOrEqual(600);
    // Outlined, never filled.
    expect(style.fill).toMatch(/rgba\(0, 0, 0, 0\)|transparent/);
    await expect(tree.locator("[data-tree-group='electronics:power']")).toBeVisible();
    await expect(tree.locator("[data-tree-category='electronics:batteries']")).toBeHidden();
  });

  test("links a group of one category straight to it", async ({ page }) => {
    await page.goto("/departments/electronics");
    await expect(sidebar(page).locator("[data-tree-group='electronics:other']")).toHaveAttribute(
      "href",
      "/departments/electronics/accessories",
    );
    await page.goto("/departments/electronics/accessories");
    await expect(sidebar(page).locator("[data-tree-group='electronics:other']")).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  test("shows an undrawn department's categories plain", async ({ page }) => {
    await page.goto("/departments/seals-bearings/seals");
    const tree = sidebar(page, "Seals & Bearings");
    // Seals & Gaskets is open; Bearings & Transmission's categories are collapsed.
    await expect(tree.locator("[data-tree-category]:visible")).toHaveCount(4);
    await expect(tree.locator("[data-tree-category] svg")).toHaveCount(0);
    await expect(tree.locator("[data-tree-group] svg")).toHaveCount(2);
    await expect(tree.locator("[data-tree-group] svg[data-icon]")).toHaveCount(0);
  });

  test("stays in view while the products scroll, and scrolls by itself", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 500 });
    await page.goto("/departments/electronics/resistors?in_stock=all&stale=all");
    const box = page.locator("#browse-tree > div");
    expect(await box.evaluate((el) => getComputedStyle(el).position)).toBe("sticky");
    expect(await box.evaluate((el) => getComputedStyle(el).overflowY)).toBe("auto");
  });

  test("puts the filters in the toolbar, with no rail and no pill", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    for (const name of ["In stock", "Checked recently", "2+ shops"]) {
      await expect(page.getByRole("link", { name })).toBeVisible();
    }
    await expect(page.locator("[data-price-chip] summary")).toHaveText(/Price/);
    await expect(page.getByRole("complementary", { name: "Filters" })).toHaveCount(0);
    await expect(page.locator("[data-browse-pill]")).toBeHidden();
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("there is no category row, only the Browse pill", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await expect(page.locator("#browse-tree")).toBeHidden();
    await expect(page.getByRole("navigation", { name: "Categories" })).toHaveCount(0);
    const pill = page.locator("[data-browse-pill]");
    await expect(pill).toBeVisible();
    await expect(pill).toHaveText(/Resistors\s*· Browse/);
    // Bottom centre.
    const box = (await pill.boundingBox())!;
    expect(Math.abs(box.x + box.width / 2 - 195)).toBeLessThan(2);
    expect(844 - (box.y + box.height)).toBeGreaterThanOrEqual(12);

    await page.goto("/departments/electronics/components");
    await expect(pill).toHaveText(/Components\s*· Browse/);
    await page.goto("/departments/electronics");
    await expect(pill).toHaveText(/Electronics\s*· Browse/);
  });

  test("opens the tree as a modal sheet, the current category marked", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.getByRole("dialog", { name: "Browse Electronics" });
    await expect(sheet).toBeVisible();
    expect(await sheet.evaluate((el) => (el as HTMLDialogElement).matches(":modal"))).toBe(true);
    const here = sheet.getByRole("link", { name: /^Resistors/ });
    await expect(here).toHaveAttribute("aria-current", "page");
    await expect(here).toBeFocused();
    // It rises from the bottom.
    const box = (await sheet.boundingBox())!;
    expect(Math.round(box.y + box.height)).toBe(844);
    // The page behind does not scroll.
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe(
      "hidden",
    );
  });

  test("traps focus while open, and returns it to the pill on Escape", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const pill = page.locator("[data-browse-pill]");
    await pill.click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() =>
        Boolean(document.activeElement?.closest("dialog[data-browse-sheet]")),
      );
      // The browser may pass focus to its own UI between the last and first
      // control; it never lands on the page behind.
      const onPage = await page.evaluate(
        () =>
          document.activeElement !== document.body &&
          !document.activeElement?.closest("dialog[data-browse-sheet]"),
      );
      expect(inside || !onPage).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(pill).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe("");
  });

  test("closes on a tap outside it", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await expect(sheet).toBeVisible();
    await page.mouse.click(195, 40);
    await expect(sheet).toBeHidden();
  });

  test("closes on a swipe down", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    const handle = (await sheet.locator("[data-sheet-handle]").boundingBox())!;
    const x = handle.x + handle.width / 2;
    const y = handle.y + 10;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x, y + 60, { steps: 4 });
    await page.mouse.move(x, y + 160, { steps: 4 });
    await page.mouse.up();
    await expect(sheet).toBeHidden();
  });

  test("closes when a category is chosen, and goes there", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await sheet.getByRole("link", { name: /^Integrated Circuits/ }).click();
    await expect(page).toHaveURL("/departments/electronics/ics");
    await expect(sheet).toBeHidden();
    await expect(page.locator("[data-browse-pill]")).toHaveText(/Integrated Circuits\s*· Browse/);
  });

  test("the pill never covers the last product", async ({ page }) => {
    await page.goto("/departments/seals-bearings?in_stock=all");
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(300);
    // Scrolled to the bottom the pill may have slid away; bring it back to measure.
    await page.mouse.wheel(0, -1);
    await expect(page.locator("[data-browse-pill]")).toHaveAttribute("data-shown", "true");
    const last = (await page.locator("[data-result=row]").last().boundingBox())!;
    const pill = (await page.locator("[data-browse-pill]").boundingBox())!;
    expect(last.y + last.height).toBeLessThanOrEqual(pill.y);
  });

  test("slides away while scrolling down and comes back on scroll up", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 500 });
    await page.goto("/departments/seals-bearings?in_stock=all");
    const pill = page.locator("[data-browse-pill]");
    await expect(pill).toHaveAttribute("data-shown", "true");
    await page.mouse.wheel(0, 300);
    await expect(pill).not.toHaveAttribute("data-shown");
    await expect.poll(() => pill.evaluate((el) => getComputedStyle(el).opacity)).toBe("0");
    await page.mouse.wheel(0, -120);
    await expect(pill).toHaveAttribute("data-shown", "true");
    // Keyboard focus always brings it back.
    await page.mouse.wheel(0, 300);
    await expect(pill).not.toHaveAttribute("data-shown");
    await pill.focus();
    await expect(pill).toHaveAttribute("data-shown", "true");
  });

  test("with reduced motion it shows and hides without animating", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 390, height: 500 });
    await page.goto("/departments/seals-bearings?in_stock=all");
    const pill = page.locator("[data-browse-pill]");
    const duration = await pill.evaluate((el) =>
      parseFloat(getComputedStyle(el).transitionDuration),
    );
    expect(duration).toBeLessThan(0.001);
    await page.mouse.wheel(0, 300);
    await expect(pill).not.toHaveAttribute("data-shown");
    await expect.poll(() => pill.evaluate((el) => getComputedStyle(el).opacity)).toBe("0");
  });

  test("with JavaScript off the pill leads to the tree on the page", async ({ browser }) => {
    const context = await browser.newContext({
      javaScriptEnabled: false,
      viewport: { width: 390, height: 844 },
    });
    const page = await context.newPage();
    await page.goto("/departments/electronics/resistors");
    await expect(page.locator("#browse-tree")).toBeHidden();
    await page.locator("[data-browse-pill]").click();
    await expect(page).toHaveURL(/#browse-tree$/);
    await expect(page.locator("#browse-tree")).toBeVisible();
    await expect(
      page.locator("#browse-tree [data-tree-category='electronics:resistors']"),
    ).toHaveAttribute("aria-current", "page");
    await context.close();
  });
});

for (const width of [320, 375, 390]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 800 } });
    for (const path of [
      "/departments/electronics",
      "/departments/electronics/components",
      "/departments/electronics/resistors",
      "/departments/seals-bearings/seals",
    ]) {
      test(`${path} does not scroll sideways`, async ({ page }) => {
        await page.goto(path);
        await noPageOverflow(page);
        await page.locator("[data-browse-pill]").click();
        await noPageOverflow(page);
      });
    }
  });
}

test.describe("both themes", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`the sheet and the pill sit on the ${scheme} surface`, async ({ browser }) => {
      const context = await browser.newContext({
        colorScheme: scheme,
        viewport: { width: 390, height: 844 },
      });
      const page = await context.newPage();
      await page.goto("/departments/electronics/resistors");
      const surface = scheme === "light" ? "rgb(255, 255, 255)" : "rgb(27, 29, 33)";
      const pill = page.locator("[data-browse-pill]");
      expect(await pill.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(surface);
      await pill.click();
      const sheet = page.locator("dialog[data-browse-sheet]");
      expect(await sheet.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(surface);
      await context.close();
    });
  }
});
