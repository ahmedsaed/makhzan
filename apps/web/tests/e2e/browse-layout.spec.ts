import { expect, test, type Locator, type Page } from "@playwright/test";

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

/** Wait until the sheet's own animations (its rise, its sinking) have run out. */
async function settled(sheet: Locator) {
  await sheet.evaluate((el) =>
    Promise.all(el.getAnimations().map((a) => a.finished.catch(() => undefined))),
  );
}

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
    await expect(toggle).toHaveAccessibleName("Subcategories of Components");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveAccessibleName("Subcategories of Components");
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

  test("opens the Price panel under its chip", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const chip = page.locator("[data-price-chip] summary");
    await chip.click();
    const panel = page.getByRole("form", { name: "Price, EGP" });
    await expect(panel).toBeVisible();
    const c = (await chip.boundingBox())!;
    const f = (await panel.boundingBox())!;
    expect(Math.abs(f.x - c.x)).toBeLessThan(2);
    expect(f.y).toBeGreaterThan(c.y + c.height);
  });

  test("leaves an empty price out of the address", async ({ page }) => {
    await page.goto("/departments/seals-bearings?in_stock=all");
    await page.locator("[data-price-chip] summary").click();
    const panel = page.getByRole("form", { name: "Price, EGP" });
    await panel.getByLabel("Min, EGP").fill("40");
    await panel.getByRole("button", { name: "Apply" }).click();
    await expect(page).toHaveURL(/min_price=40/);
    expect(page.url()).not.toMatch(/max_price/);
    await page.locator("[data-price-chip] summary").click();
    await panel.getByLabel("Min, EGP").fill("");
    await panel.getByRole("button", { name: "Apply" }).click();
    await expect(page).not.toHaveURL(/min_price/);
    expect(page.url()).not.toMatch(/max_price/);
    expect(page.url()).toMatch(/in_stock=all/);
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

  test("the filter chips fade at the edge they hide, Price among the first", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const bar = page.getByRole("navigation", { name: "Quick filters" });
    await expect(bar).toHaveAttribute("data-more-end", "true");
    expect(await bar.evaluate((el) => getComputedStyle(el).maskImage)).toMatch(/^linear-gradient/);
    // Price comes before "2+ shops" and starts on screen.
    const order = await bar.evaluate((el) =>
      [...el.children].map((c) => (c.querySelector("summary") ?? c).textContent?.trim()),
    );
    expect(order.slice(0, 4)).toEqual(["In stock", "Checked recently", "Price", "2+ shops"]);
    const price = (await page.locator("[data-price-chip] summary").boundingBox())!;
    expect(price.x).toBeLessThan(390 - 32);
    // At the end the fade goes.
    await bar.evaluate((el) => (el.scrollLeft = el.scrollWidth));
    await expect(bar).not.toHaveAttribute("data-more-end");
  });

  for (const width of [320, 390]) {
    test(`the Price panel is drawn and usable at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.goto("/departments/seals-bearings?in_stock=all");
      await page.locator("[data-price-chip] summary").click();
      const panel = page.getByRole("form", { name: "Price, EGP" });
      const f = (await panel.boundingBox())!;
      expect(f.x).toBeGreaterThanOrEqual(15);
      expect(f.x + f.width).toBeLessThanOrEqual(width - 15);
      // Drawn, not just laid out: the chip bar's fade is a mask, which would
      // clip the panel (toBeVisible cannot see that). What is at its centre?
      const hit = await page.evaluate(
        ([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest("form[aria-label]")),
        [f.x + f.width / 2, f.y + f.height / 2],
      );
      expect(hit).toBe(true);
      // And it works by pointer, at the coordinates a finger would use.
      const min = (await panel.getByLabel("Min, EGP").boundingBox())!;
      await page.mouse.click(min.x + min.width / 2, min.y + min.height / 2);
      await page.keyboard.type("40");
      const apply = (await panel.getByRole("button", { name: "Apply" }).boundingBox())!;
      await page.mouse.click(apply.x + apply.width / 2, apply.y + apply.height / 2);
      await expect(page).toHaveURL(/min_price=40/);
      await noPageOverflow(page);
    });
  }

  test("the Price panel follows its chip when the bar scrolls", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    // A panel narrow enough not to be clamped, so where it sits is the chip's.
    await page.addStyleTag({ content: "form[aria-label='Price, EGP'] { width: 4rem; }" });
    await page.locator("[data-price-chip] summary").click();
    const offset = () =>
      page.evaluate(() => {
        const panel = document.querySelector<HTMLElement>("form[aria-label='Price, EGP']")!;
        const chip = document.querySelector("[data-price-chip] summary")!;
        return Math.round(panel.getBoundingClientRect().left - chip.getBoundingClientRect().left);
      });
    await expect.poll(offset).toBe(0);
    const bar = page.getByRole("navigation", { name: "Quick filters" });
    await bar.evaluate((el) => {
      el.style.scrollBehavior = "auto";
      el.scrollLeft = el.scrollWidth;
    });
    // The chip moved left with the bar; the panel moved with it.
    await expect.poll(offset).toBe(0);
  });

  test("the fade follows chips that change width, with no scroll", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const bar = page.getByRole("navigation", { name: "Quick filters" });
    expect(await bar.evaluate((el) => el.scrollLeft)).toBe(0);
    await expect(bar).toHaveAttribute("data-more-end", "true");
    // Every chip shrinks (as a long price label would give way to "Price")
    // while the bar keeps its size and is never scrolled: only watching the
    // chips themselves can notice that nothing overflows any more.
    await bar.evaluate((el) => {
      for (const chip of el.children) {
        const box = chip as HTMLElement;
        box.style.width = "40px";
        box.style.overflow = "hidden";
      }
    });
    await expect(bar).not.toHaveAttribute("data-more-end");
    expect(await bar.evaluate((el) => el.scrollLeft)).toBe(0);
  });

  test("tapping Price brings it into view at 320px", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    await page.goto("/departments/electronics/resistors");
    const bar = page.getByRole("navigation", { name: "Quick filters" });
    const chip = page.locator("[data-price-chip] summary");
    await chip.dispatchEvent("click");
    await expect(page.getByRole("form", { name: "Price, EGP" })).toBeVisible();
    const fits = await chip.evaluate((el) => {
      const box = el.getBoundingClientRect();
      const row = el.closest("[data-scroll-fade]")!.getBoundingClientRect();
      return box.left >= row.left - 1 && box.right <= row.right + 1;
    });
    expect(fits).toBe(true);
    expect(await bar.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
  });

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
    await settled(sheet);
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
    // The scroll lock is released by the dialog's close event, a task after it hides.
    await expect.poll(() => page.evaluate(() => document.documentElement.style.overflow)).toBe("");
  });

  test("closes on a mouse click on Close", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const pill = page.locator("[data-browse-pill]");
    await pill.click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await settled(sheet);
    const close = (await sheet.getByRole("button", { name: "Close" }).boundingBox())!;
    // A real mouse press and release on the button inside the swipe handle.
    await page.mouse.move(close.x + close.width / 2, close.y + close.height / 2);
    await page.mouse.down();
    await page.mouse.up();
    await expect(sheet).toBeHidden();
    await expect(pill).toBeFocused();
  });

  test("puts focus on the pill after a dismissal even if a tap did not focus it", async ({
    page,
  }) => {
    // Safari and Firefox on macOS do not focus a link on click, so the dialog's
    // own restore would return focus to the body. Open it as they would.
    await page.goto("/departments/electronics/resistors");
    const pill = page.locator("[data-browse-pill]");
    await pill.evaluate((el) => (el as HTMLElement).blur());
    await pill.dispatchEvent("click");
    const sheet = page.locator("dialog[data-browse-sheet]");
    await expect(sheet).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(pill).toBeFocused();
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
    await settled(sheet);
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

  test("returns focus to the pill after a tap outside", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const pill = page.locator("[data-browse-pill]");
    await pill.click();
    await page.mouse.click(195, 40);
    await expect(page.locator("dialog[data-browse-sheet]")).toBeHidden();
    await expect(pill).toBeFocused();
  });

  test("a short drag released off the handle springs back", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await settled(sheet);
    const handle = (await sheet.locator("[data-sheet-handle]").boundingBox())!;
    const x = handle.x + handle.width / 2;
    await page.mouse.move(x, handle.y + 10);
    await page.mouse.down();
    await page.mouse.move(x, handle.y + 50, { steps: 4 });
    // Released well away from the handle, over the list.
    await page.mouse.move(x, 700, { steps: 2 });
    await page.mouse.move(x, handle.y + 50, { steps: 2 });
    await page.mouse.up();
    await expect(sheet).toBeVisible();
    // The pointer was captured, so the release ended the gesture: no stale
    // offset once the spring-back has settled, and the mouse no longer moves it.
    await page.mouse.move(x, 760);
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLElement).style.transform)).toBe("");
  });

  test("turning the phone on its side closes the sheet and frees the page", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await expect(sheet).toBeVisible();
    await page.setViewportSize({ width: 844, height: 390 });
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(false);
    await expect.poll(() => page.evaluate(() => document.documentElement.style.overflow)).toBe("");
    // The sidebar shows, and works: nothing is left inert.
    await sidebar(page).locator("[data-tree-category='electronics:ics']").click();
    await expect(page).toHaveURL("/departments/electronics/ics");
  });

  test("the results leave room for the pill under the last product", async ({ page }) => {
    await page.goto("/departments/seals-bearings?in_stock=all");
    // Scroll so the end of the results column meets the bottom of the screen:
    // where the last card would sit under the pill if the column left no room.
    await page.evaluate(() => {
      const main = document.querySelector("[data-browse-main]")!;
      const end = main.getBoundingClientRect().bottom + window.scrollY - window.innerHeight;
      window.scrollTo(0, end);
    });
    const pill = page.locator("[data-browse-pill]");
    await pill.focus(); // brings it back if the scroll hid it
    await expect(pill).toHaveAttribute("data-shown", "true");
    const main = (await page.locator("[data-browse-main]").boundingBox())!;
    expect(Math.abs(main.y + main.height - 844)).toBeLessThan(2);
    const last = (await page.locator("[data-result=row]").last().boundingBox())!;
    const box = (await pill.boundingBox())!;
    expect(last.y + last.height).toBeLessThanOrEqual(box.y);
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

// The owner's sheet-motion mockup, option A with the funnel (18 November 2026).
test.describe("the phone sheet, option A", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  async function openSheet(page: Page) {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    return page.locator("dialog[data-browse-sheet]");
  }

  test("a group is two separate tinted buttons, 44px, 6px apart", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    const node = sheet.locator("[data-tree-node='electronics:tools']");
    const name = node.locator("[data-tree-group]");
    const funnel = node.locator("button[data-funnel]");
    const n = (await name.boundingBox())!;
    const f = (await funnel.boundingBox())!;
    expect(Math.round(n.height)).toBe(44);
    expect(Math.round(f.height)).toBe(44);
    expect(Math.round(f.width)).toBe(44);
    expect(Math.round(f.x - (n.x + n.width))).toBe(6);
    const style = (el: Locator) =>
      el.evaluate((e) => {
        const s = getComputedStyle(e);
        return { bg: s.backgroundColor, radius: s.borderTopLeftRadius };
      });
    const ns = await style(name);
    const fs = await style(funnel);
    expect(ns.bg).toBe(fs.bg);
    expect(ns.bg).not.toMatch(/rgba\(0, 0, 0, 0\)/);
    expect(ns.radius).toBe("8px");
    expect(fs.radius).toBe("8px");
    await expect(funnel.locator("svg[data-icon='funnel'] path")).toHaveCount(1);
    await expect(funnel).toHaveAccessibleName("Subcategories of Tools & Equipment");
  });

  test("an open group's funnel fills solid in chip-on", async ({ page }) => {
    const sheet = await openSheet(page);
    const chipOn = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.className = "bg-chip-on";
      document.body.append(probe);
      const color = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return color;
    });
    const components = sheet.locator(
      "[data-tree-node='electronics:components'] button[data-funnel]",
    );
    await expect(components).toHaveAttribute("aria-expanded", "true");
    await expect
      .poll(() => components.evaluate((e) => getComputedStyle(e).backgroundColor))
      .toBe(chipOn);
    const power = sheet.locator("[data-tree-node='electronics:tools'] button[data-funnel]");
    expect(await power.evaluate((e) => getComputedStyle(e).backgroundColor)).not.toBe(chipOn);
    await power.click();
    await expect(power).toHaveAttribute("aria-expanded", "true");
    await expect
      .poll(() => power.evaluate((e) => getComputedStyle(e).backgroundColor))
      .toBe(chipOn);
  });

  test("a group opens by grid rows, its categories in the page all along", async ({ page }) => {
    const sheet = await openSheet(page);
    const fold = sheet.locator("[data-tree-node='electronics:tools'] [data-fold]");
    expect(await fold.evaluate((e) => getComputedStyle(e).transitionProperty)).toContain(
      "grid-template-rows",
    );
    expect(await fold.evaluate((e) => getComputedStyle(e).transitionDuration)).toBe("0.25s");
    expect(await fold.evaluate((e) => e.getBoundingClientRect().height)).toBe(0);
    await expect(fold.locator("a[href='/departments/electronics/soldering']")).toHaveCount(1);
    await sheet.locator("[data-tree-node='electronics:tools'] button[data-funnel]").click();
    await expect
      .poll(() => fold.evaluate((e) => e.getBoundingClientRect().height))
      .toBeGreaterThan(40);
    await expect(fold.locator("a[href='/departments/electronics/soldering']")).toBeVisible();
  });

  test("a single-link group keeps both buttons, the funnel disabled", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    // Accessories & Other holds one category: its name goes straight there.
    const name = sheet.locator("[data-tree-group='electronics:other']");
    await expect(name).toHaveAttribute("href", "/departments/electronics/accessories");
    const funnel = name.locator("xpath=ancestor::li[1]").locator("button");
    await expect(funnel).toBeDisabled();
    await expect(funnel).toHaveAccessibleName("No subcategories in Accessories & Other");
    await expect(funnel).not.toHaveAttribute("aria-expanded");
    // The same widths as a group that opens.
    const otherName = (await name.boundingBox())!;
    const otherFunnel = (await funnel.boundingBox())!;
    const tools = sheet.locator("[data-tree-node='electronics:tools']");
    const toolsName = (await tools.locator("[data-tree-group]").boundingBox())!;
    const toolsFunnel = (await tools.locator("button[data-funnel]").boundingBox())!;
    expect(Math.abs(otherName.width - toolsName.width)).toBeLessThan(1);
    expect(Math.abs(otherFunnel.width - toolsFunnel.width)).toBeLessThan(1);
    expect(Math.abs(otherFunnel.x - toolsFunnel.x)).toBeLessThan(1);
    // Dimmed, no pointer, and out of the tab order.
    expect(await funnel.evaluate((e) => getComputedStyle(e).cursor)).toBe("default");
    await funnel.evaluate((e) => (e as HTMLElement).focus());
    await expect(funnel).not.toBeFocused();
    // A tap does nothing: still open, still here, nothing expanded.
    await funnel.click({ force: true });
    expect(await sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(true);
    await expect(page).toHaveURL("/departments/electronics/resistors");
    await expect(sheet.locator("[aria-expanded='true']")).toHaveCount(1); // Components, the page's own
  });

  test("it rises over 250ms, then rests open", async ({ page }) => {
    const sheet = await openSheet(page);
    const running = await sheet.evaluate((el) =>
      el.getAnimations().map((a) => (a.effect as KeyframeEffect).getTiming().duration),
    );
    expect(running).toContain(250);
    await settled(sheet);
    expect(await sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(true);
    expect(await sheet.evaluate((el) => getComputedStyle(el).transform)).toBe("none");
    expect(await sheet.evaluate((el) => el.getAnimations().length)).toBe(0);
  });

  test("it sinks over 200ms before it closes", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    await sheet.getByRole("button", { name: "Close" }).click();
    // Still open while it slides away.
    const during = await sheet.evaluate((el) => ({
      open: (el as HTMLDialogElement).open,
      closing: el.hasAttribute("data-closing"),
      durations: el.getAnimations().map((a) => (a.effect as KeyframeEffect).getTiming().duration),
    }));
    expect(during).toEqual({ open: true, closing: true, durations: [200] });
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(false);
    expect(await sheet.evaluate((el) => el.hasAttribute("data-closing"))).toBe(false);
    await expect(page.locator("[data-browse-pill]")).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe("");
  });

  test("Escape slides it away too", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    await page.keyboard.press("Escape");
    expect(await sheet.evaluate((el) => el.hasAttribute("data-closing"))).toBe(true);
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(false);
    await expect(page.locator("[data-browse-pill]")).toBeFocused();
  });

  test("under reduced motion it opens and closes at once", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const sheet = await openSheet(page);
    const durations = await sheet.evaluate((el) =>
      el.getAnimations().map((a) => (a.effect as KeyframeEffect).getTiming().duration),
    );
    for (const d of durations) expect(d).toBeLessThan(1);
    await sheet.getByRole("button", { name: "Close" }).click();
    // No wait for an animation: closed by the time the click returns.
    expect(await sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(false);
    expect(await page.evaluate(() => document.documentElement.style.overflow)).toBe("");
  });

  test("a swipe past the threshold glides out, then closes", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    const handle = (await sheet.locator("[data-sheet-handle]").boundingBox())!;
    const x = handle.x + handle.width / 2;
    const y = handle.y + 10;
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let step = 1; step <= 10; step++) {
      await page.mouse.move(x, y + step * 20);
      // The sheet follows the finger.
      if (step === 5) {
        expect(await sheet.evaluate((el) => (el as HTMLElement).style.transform)).toBe(
          "translateY(100px)",
        );
      }
    }
    await page.mouse.up();
    const glide = await sheet.evaluate((el) => ({
      open: (el as HTMLDialogElement).open,
      transition: (el as HTMLElement).style.transition,
    }));
    expect(glide.open).toBe(true);
    const ms = Number(
      /transform (\d+)ms cubic-bezier\(0\.25, 0\.6, 0\.4, 1\)/.exec(glide.transition)?.[1],
    );
    expect(ms).toBeGreaterThanOrEqual(120);
    expect(ms).toBeLessThanOrEqual(240);
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(false);
    await expect(page.locator("[data-browse-pill]")).toBeFocused();
  });

  test("a short, slow swipe springs back with an overshoot", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    const handle = (await sheet.locator("[data-sheet-handle]").boundingBox())!;
    const x = handle.x + handle.width / 2;
    const y = handle.y + 10;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x, y + 40, { steps: 8 });
    await page.waitForTimeout(120); // held still: no flick
    await page.mouse.up();
    const back = await sheet.evaluate((el) => (el as HTMLElement).style.transition);
    expect(back).toBe("transform 380ms cubic-bezier(0.3, 1.35, 0.5, 1)");
    expect(await sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(true);
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLElement).style.transform)).toBe("");
    expect(await sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(true);
  });

  test("a quick flick closes even a short swipe", async ({ page }) => {
    const sheet = await openSheet(page);
    await settled(sheet);
    const handle = (await sheet.locator("[data-sheet-handle]").boundingBox())!;
    const x = handle.x + handle.width / 2;
    const y = handle.y + 10;
    // Dispatched a frame apart: 60px at about 0.9px/ms, under the 80px threshold.
    await sheet.locator("[data-sheet-handle]").evaluate(
      (el, [px, py]) => {
        const at = (type: string, cy: number) =>
          el.dispatchEvent(
            new PointerEvent(type, {
              bubbles: true,
              pointerId: 7,
              pointerType: "touch",
              clientX: px,
              clientY: cy,
            }),
          );
        at("pointerdown", py);
        return new Promise<void>((done) => {
          let cy = py;
          const step = () => {
            cy += 15;
            at("pointermove", cy);
            if (cy < py + 60) requestAnimationFrame(step);
            else {
              at("pointerup", cy);
              done();
            }
          };
          requestAnimationFrame(step);
        });
      },
      [x, y],
    );
    await expect.poll(() => sheet.evaluate((el) => (el as HTMLDialogElement).open)).toBe(false);
  });
});

// Review follow-ups for the option A sheet.
test.describe("the phone sheet, closing edge cases", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  const isOpen = (sheet: Locator) => sheet.evaluate((el) => (el as HTMLDialogElement).open);

  test("after a double Escape the next opening stays open", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const pill = page.locator("[data-browse-pill]");
    const sheet = page.locator("dialog[data-browse-sheet]");
    await pill.click();
    await settled(sheet);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await expect.poll(() => isOpen(sheet)).toBe(false);
    await pill.click();
    await page.waitForTimeout(600);
    expect(await isOpen(sheet)).toBe(true);
  });

  test("widening past md mid-close leaves no close behind for the next opening", async ({
    page,
  }) => {
    await page.goto("/departments/electronics/resistors");
    const pill = page.locator("[data-browse-pill]");
    const sheet = page.locator("dialog[data-browse-sheet]");
    await pill.click();
    await settled(sheet);
    await sheet.getByRole("button", { name: "Close" }).click();
    expect(await sheet.evaluate((el) => el.hasAttribute("data-closing"))).toBe(true);
    await page.setViewportSize({ width: 844, height: 390 });
    await expect.poll(() => isOpen(sheet)).toBe(false);
    await page.setViewportSize({ width: 390, height: 844 });
    await pill.click();
    await page.waitForTimeout(600);
    expect(await isOpen(sheet)).toBe(true);
  });

  test("Escape during a swipe's glide lets the glide close it, with no jump", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await settled(sheet);
    const handle = (await sheet.locator("[data-sheet-handle]").boundingBox())!;
    const x = handle.x + handle.width / 2;
    const y = handle.y + 10;
    await page.mouse.move(x, y);
    await page.mouse.down();
    for (let step = 1; step <= 10; step++) await page.mouse.move(x, y + step * 20);
    await page.mouse.up();
    await page.keyboard.press("Escape");
    // Still on its way out from where the finger left it: never back at the top.
    const after = await sheet.evaluate((el) => ({
      transform: (el as HTMLElement).style.transform,
      closing: el.hasAttribute("data-closing"),
    }));
    expect(after.transform).toMatch(/^translateY\([1-9]\d*(\.\d+)?px\)$/);
    expect(after.closing).toBe(false);
    await expect.poll(() => isOpen(sheet)).toBe(false);
  });

  test("an open group's categories have room for a focus ring", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    await page.locator("[data-browse-pill]").click();
    const sheet = page.locator("dialog[data-browse-sheet]");
    await settled(sheet);
    const room = await sheet
      .locator("[data-tree-node='electronics:components'] [data-fold] > div")
      .evaluate((clip) => {
        const box = clip.getBoundingClientRect();
        const links = [...clip.querySelectorAll("a")].map((a) => a.getBoundingClientRect());
        return {
          top: links[0].top - box.top,
          bottom: box.bottom - links[links.length - 1].bottom,
          right: Math.min(...links.map((l) => box.right - l.right)),
        };
      });
    // A 2px ring 2px out reaches 4px past the button.
    expect(room.top).toBeGreaterThanOrEqual(4);
    expect(room.bottom).toBeGreaterThanOrEqual(4);
    expect(room.right).toBeGreaterThanOrEqual(4);
  });

  test("the current category shows the focus ring under keyboard focus", async ({ page }) => {
    await page.goto("/departments/electronics/resistors");
    const link = await linkColour(page);
    const pill = page.locator("[data-browse-pill]");
    await pill.focus();
    await page.keyboard.press("Enter");
    const sheet = page.locator("dialog[data-browse-sheet]");
    await settled(sheet);
    const here = sheet.getByRole("link", { name: /^Resistors/ });
    await expect(here).toBeFocused();
    // Move away and back by keyboard, so focus is plainly keyboard focus.
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    await expect(here).toBeFocused();
    const ring = await here.evaluate((el) => {
      const s = getComputedStyle(el);
      return {
        colour: s.outlineColor,
        offset: s.outlineOffset,
        visible: el.matches(":focus-visible"),
      };
    });
    expect(ring).toEqual({ colour: link, offset: "2px", visible: true });
    // Unfocused, it is the current-place outline again.
    await page.keyboard.press("Tab");
    expect(await here.evaluate((el) => getComputedStyle(el).outlineOffset)).toBe("-2px");
  });
});

test("the sidebar's current item shows the focus ring under keyboard focus", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/departments/electronics/resistors");
  const link = await linkColour(page);
  const here = sidebar(page).locator("[data-tree-category='electronics:resistors']");
  // Reach it by keyboard from its group's chevron, through the categories before it.
  await sidebar(page).locator("[data-tree-node='electronics:components'] button").focus();
  for (let i = 0; i < 6 && !(await here.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(here).toBeFocused();
  const ring = await here.evaluate((el) => {
    const s = getComputedStyle(el);
    return { colour: s.outlineColor, offset: s.outlineOffset };
  });
  expect(ring).toEqual({ colour: link, offset: "2px" });
});

/** The `link` token as the browser computes it. */
async function linkColour(page: Page) {
  return page.evaluate(() => {
    const probe = document.createElement("span");
    probe.className = "text-link";
    document.body.append(probe);
    const colour = getComputedStyle(probe).color;
    probe.remove();
    return colour;
  });
}
