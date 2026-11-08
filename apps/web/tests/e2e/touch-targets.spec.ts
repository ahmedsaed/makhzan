import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * Rule S4 on a phone: every main control is at least 44px tall to a finger.
 *
 * Measured as the browser hit-tests it, not as the box is drawn: a chip is
 * drawn 36px tall with an invisible extension above and below, and what
 * counts is where a tap lands. So the height is the run of points along the
 * control's vertical centre line that `elementFromPoint` resolves to it.
 */

test.use({ viewport: { width: 390, height: 844 } });

const MIN = 44;

/** The control's tappable height, in CSS pixels. */
async function tapHeight(control: Locator): Promise<number> {
  return control.evaluate((element) => {
    element.scrollIntoView({ block: "center" });
    const box = element.getBoundingClientRect();
    const x = box.left + Math.min(box.width / 2, 8);
    const hits = (y: number) => {
      const found = document.elementFromPoint(x, y);
      return found !== null && (found === element || element.contains(found));
    };
    let top = box.top + box.height / 2;
    let bottom = top;
    while (top > box.top - 24 && hits(top - 1)) top -= 1;
    while (bottom < box.bottom + 24 && hits(bottom + 1)) bottom += 1;
    return bottom - top + 1;
  });
}

async function expectTappable(page: Page, controls: Record<string, Locator>) {
  for (const [name, control] of Object.entries(controls)) {
    await expect(control, name).toBeVisible();
    expect(await tapHeight(control), name).toBeGreaterThanOrEqual(MIN);
  }
}

test("the search page's controls", async ({ page }) => {
  await page.goto("/search?q=relay");
  await expectTappable(page, {
    "In stock chip": page.getByRole("link", { name: "In stock" }),
    "2+ shops chip": page.getByRole("link", { name: "2+ shops" }),
    "Category, price chip": page.locator("summary", { hasText: "Category, price" }),
    "out of stock link": page.getByRole("link", { name: "6 more out of stock" }),
    sort: page.getByRole("combobox"),
    "list view": page.getByRole("button", { name: "List view" }),
    "grid view": page.getByRole("button", { name: "Grid view" }),
    "next page": page.getByRole("link", { name: "Next" }),
    "top category": page
      .getByRole("region", { name: /Top categories/ })
      .getByRole("link")
      .first(),
  });

  await page.goto("/search?q=relay&shop=shop-a");
  await expectTappable(page, {
    "search all shops": page.getByRole("link", { name: "Search all shops" }),
  });
});

test("a trade page's controls", async ({ page }) => {
  await page.goto("/trades/seals-bearings");
  await expectTappable(page, {
    "back to all trades": page.getByRole("link", { name: "All trades", exact: true }),
    "In stock chip": page.getByRole("link", { name: "In stock" }),
    "2+ shops chip": page.getByRole("link", { name: "2+ shops" }),
    "out of stock link": page.getByRole("link", { name: "2 more out of stock" }),
    sort: page.getByRole("combobox"),
    "list view": page.getByRole("button", { name: "List view" }),
    "group tile": page.getByRole("navigation", { name: "Groups" }).getByRole("link").first(),
  });

  await page.goto("/trades/seals-bearings/oil-seals");
  const crumbs = page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link");
  await expect(crumbs).toHaveCount(3);
  for (const index of [0, 1, 2]) {
    await expectTappable(page, { [`breadcrumb ${index}`]: crumbs.nth(index) });
  }
});

test("the product page's controls", async ({ page }) => {
  await page.goto("/products/p-single");
  const crumbs = page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link");
  await expectTappable(page, {
    "bottom bar button": page.locator("[data-bottom-bar]").getByRole("link", { name: /View at/ }),
    "first breadcrumb": crumbs.first(),
    "sold by card": page.locator("[data-sold-by]"),
    "similar fact": page.locator("[data-fact=similar] a"),
    "next photo": page.getByRole("button", { name: "Next photo" }),
    "next similar products": page.getByRole("button", { name: "Next products" }),
  });

  await page.locator('a[data-photo="0"]').click();
  const viewer = page.locator("dialog[data-viewer]");
  await expectTappable(page, {
    "viewer close": viewer.getByRole("button", { name: "Close" }),
    "viewer next": viewer.getByRole("button", { name: "Next photo" }),
  });
  await page.keyboard.press("Escape");

  await page.goto("/products/p-specs");
  await expectTappable(page, { "datasheet link": page.locator("[data-datasheet]").first() });
});

test("nothing scrolls sideways at 320px on the trade pages", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  for (const path of ["/trades/seals-bearings", "/trades/seals-bearings/oil-seals"]) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});
