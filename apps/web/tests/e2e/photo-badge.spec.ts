import { expect, test } from "@playwright/test";

/**
 * The badge on every product photo naming the shop it comes from: drawn over
 * the photo by the page, never baked into it (the <img> is the shop's own
 * file, decision 0003), hidden from screen readers with the shop in the alt
 * text instead. Fixtures: tests/e2e/fixtures/photo-shop.mjs.
 */

const PHONE = { width: 390, height: 844 };
const NARROW = { width: 320, height: 700 };
const LONG_SHOP = "Shop B Electronics and Components Egypt";

test.describe("on a product page", () => {
  test("each photo in the gallery names its own shop", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/products/p-two-shops");
    const slides = page.locator("[data-gallery] a[data-photo]");
    await expect(slides).toHaveCount(3);
    const badge = (index: number) => slides.nth(index).locator("[data-photo-shop]");
    await expect(badge(0)).toHaveText("Shop A");
    await expect(badge(1)).toHaveText("Shop A");
    await expect(badge(2)).toHaveText(LONG_SHOP);
    await expect(badge(0)).toHaveAttribute("aria-hidden", "true");

    // The shop is said once, in the alt text, and the photo is the shop's file.
    const img = slides.nth(2).locator("img");
    await expect(img).toHaveAttribute(
      "alt",
      `SG90 Micro Servo 9g, photo 3 — photo from ${LONG_SHOP}`,
    );
    await expect(img).toHaveAttribute("src", /\/img\/photo\.png\?from=b1$/);
  });

  test("a long name is cut short of the photo counter", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/products/p-two-shops");
    const slide = page.locator("[data-gallery] [data-photo-count]").nth(2);
    await slide.scrollIntoViewIfNeeded();
    const badge = await slide.locator("[data-photo-shop]").boundingBox();
    const count = await slide.locator("span.tabular").boundingBox();
    expect(badge && count).toBeTruthy();
    expect(badge!.x + badge!.width).toBeLessThan(count!.x);
    // One line, truncated.
    expect(badge!.height).toBeLessThan(24);
  });

  test("the full-size viewer badges each photo too", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/products/p-two-shops");
    await page.locator('[data-gallery] a[data-photo="2"]').click();
    const viewer = page.locator("dialog[data-viewer]");
    await expect(viewer).toBeVisible();
    const slide = viewer.locator('[data-viewer-slide="2"]');
    await expect(slide.locator("[data-photo-shop]")).toHaveText(LONG_SHOP);
    await expect(viewer.locator('[data-viewer-slide="0"] [data-photo-shop]')).toHaveText("Shop A");
  });

  test("similar products credit their photos, and an older summary simply has no badge", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/products/p-two-shops");
    const credited = page.locator('li[data-result="card"]', { hasText: "MG996R Servo" });
    await expect(credited.locator("[data-photo-shop]")).toHaveText(LONG_SHOP);
    const old = page.locator('li[data-result="card"]', { hasText: "MG90S Servo" });
    await expect(old.locator("img")).toHaveAttribute("alt", "MG90S Servo");
    await expect(old.locator("[data-photo-shop]")).toHaveCount(0);
  });

  test("the badge reads the same in dark mode: dark fill, white text", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/products/p-two-shops");
    await expect(page.locator("html")).toHaveClass(/dark/);
    const badge = page.locator('[data-gallery] a[data-photo="0"] [data-photo-shop]');
    await expect(badge).toHaveCSS("color", "rgb(255, 255, 255)");
    const fill = await badge.evaluate((el) => getComputedStyle(el).backgroundColor);
    // 21, 23, 28 at 80%, however the browser spells it.
    expect(fill).toMatch(/0\.8\)$|\/ 0\.8\)$/);
  });
});

test.describe("on search results", () => {
  test("a grid card credits its photo; the uncredited and the photoless have no badge", async ({
    page,
  }) => {
    await page.addInitScript(() => window.localStorage.setItem("makhzan:view", "grid"));
    await page.goto("/search?q=photobadge");
    const card = (title: string) => page.locator('li[data-result="card"]', { hasText: title });
    await expect(card("Alpha servo, credited").locator("[data-photo-shop]")).toHaveText(LONG_SHOP);
    await expect(card("Alpha servo, credited").locator("img")).toHaveAttribute(
      "alt",
      `Alpha servo, credited — photo from ${LONG_SHOP}`,
    );
    await expect(card("Bravo servo, no credit").locator("[data-photo-shop]")).toHaveCount(0);
    await expect(card("Bravo servo, no credit").locator("img")).toHaveAttribute(
      "alt",
      "Bravo servo, no credit",
    );
    await expect(card("without a photo").locator("[data-photo-shop]")).toHaveCount(0);
    await expect(card("without a photo").locator('[data-media="fallback"]')).toHaveCount(1);
  });

  test("a list row's small thumbnail credits the shop in alt and title only", async ({ page }) => {
    await page.goto("/search?q=photobadge");
    const row = page.locator('li[data-result="row"]', { hasText: "Alpha servo, credited" });
    await expect(row.locator("[data-photo-shop]")).toHaveCount(0);
    await expect(row.locator("img")).toHaveAttribute("title", `Photo from ${LONG_SHOP}`);
  });

  for (const view of ["list", "grid"] as const) {
    test(`nothing scrolls sideways at 320px (${view})`, async ({ page }) => {
      await page.addInitScript((v) => window.localStorage.setItem("makhzan:view", v), view);
      await page.setViewportSize(NARROW);
      await page.goto("/search?q=photobadge");
      await expect(page.locator(`[data-view="${view}"]`)).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBe(0);
      if (view === "grid") {
        // The long name stays inside its card.
        const card = page.locator('li[data-result="card"]', { hasText: "Alpha servo, credited" });
        const box = (await card.boundingBox())!;
        const badge = (await card.locator("[data-photo-shop]").boundingBox())!;
        expect(badge.x + badge.width).toBeLessThanOrEqual(box.x + box.width);
      }
    });
  }
});

test("a product page at 320px keeps the badge inside the page", async ({ page }) => {
  await page.setViewportSize(NARROW);
  await page.goto("/products/p-two-shops");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
});

test("on a phone, the several-shop product's thumbnail credits its shop", async ({ page }) => {
  await page.setViewportSize(PHONE);
  await page.goto("/products/p-two-shops");
  // The thumbnail sits beside the title's column (h1 › its row with the
  // report button › the column › the row with the thumbnail).
  const thumb = page.locator("h1").locator("xpath=../../..").locator("img").first();
  await expect(thumb).toHaveAttribute("alt", "SG90 Micro Servo 9g — photo from Shop A");
  await expect(page.locator('[data-photo-shop="compact"]:visible')).toHaveText("Shop A");
});
