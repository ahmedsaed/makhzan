import { expect, test } from "@playwright/test";

/**
 * Price history on two production products (tests/e2e/fixtures/real-history.*):
 * a stale offer's lone seeded point from August must not stretch the chart
 * back to a time when no counted shop had a point, nor label that stretch
 * "not checked since" a later date.
 */

const TB6600 = "2b43372b-4471-4a32-81c5-9aae1cf32059";
const UT33D = "2c6f64b4-3855-40ec-998d-aa88b4f5ae59";

test.use({ viewport: { width: 1280, height: 900 } });

test("TB6600: the chart starts with the fresh shops' data, with no gap", async ({ page }) => {
  await page.goto(`/products/${TB6600}`);
  const card = page.locator("[data-history=price]");
  await expect(card.locator("[data-gap]")).toHaveCount(0);
  // Dates move with the suite's clock (the fixture is shifted to today); on
  // the snapshot's day this read "since 14 Oct", not "since 24 Aug".
  await expect(card).toContainText(/since \d+ \w+/);
  await expect(card).not.toContainText("last 90 days");
  await expect(card.locator("[data-history-lowest]")).toContainText("EGP 425");
  await expect(page.locator("[data-fact=history]")).toContainText(/^Lowest since \d+ \w+ EGP 425/);
});

test("UT33D+: under 30 days of counted recording, so no card and no line", async ({ page }) => {
  await page.goto(`/products/${UT33D}`);
  await expect(page.locator("h1")).toContainText("UT33D");
  await expect(page.locator("[data-history]")).toHaveCount(0);
  await expect(page.locator("[data-fact=history]")).toHaveCount(0);
});
