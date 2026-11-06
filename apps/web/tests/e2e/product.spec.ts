import { expect, test } from "@playwright/test";

/** The page the whole system exists to render. */

test("offers come before the description in the document", async ({ page }) => {
  // That DOM order is what puts offers above the supplier's prose on a phone.
  await page.goto("/en/products/prod-1");
  const html = (await page.content()).replace(/\s+/g, " ");
  const offers = html.indexOf("offers");
  const similar = html.indexOf("Related products");
  expect(offers).toBeGreaterThan(-1);
  expect(similar).toBeGreaterThan(offers);
});

test("an offer with no price stays visible and is not shown as free", async ({ page }) => {
  await page.goto("/en/products/prod-1");
  await expect(page.getByText("Price on request")).toBeVisible();
  await expect(page.getByText(/EGP\s*0(\.00)?\b/)).toHaveCount(0);
});

test("the hand-off leaves the site and is not followed by crawlers", async ({ page }) => {
  await page.goto("/en/products/prod-1");
  const handoff = page.getByRole("link", { name: /Visit/ }).first();
  await expect(handoff).toHaveAttribute("href", "https://shop-a.test/p/esp32");
  await expect(handoff).toHaveAttribute("target", "_blank");
  await expect(handoff).toHaveAttribute("rel", /nofollow/);
});

test("a listing links back up to the comparison", async ({ page }) => {
  // Without this the page is a dead end that competes with the supplier's site.
  await page.goto("/en/listings/listing-1");
  await expect(page.getByRole("link", { name: /See other suppliers/ })).toHaveAttribute(
    "href",
    "/en/products/prod-1",
  );
});

test("a withdrawn listing is a tombstone, not a 404", async ({ page }) => {
  const response = await page.goto("/en/listings/listing-gone");
  expect(response?.status()).toBe(200);
  await expect(page.getByText("This listing was withdrawn")).toBeVisible();
  // It keeps its URL but must leave the index.
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
});

test("a missing product is a real 404", async ({ page }) => {
  const response = await page.goto("/en/products/does-not-exist");
  expect(response?.status()).toBe(404);
});

test("a product with no photo shows the fallback, not a broken image", async ({ page }) => {
  // 375 listings have no photo and supplier URLs rot, so this is a real state.
  await page.goto("/en/products/prod-1");
  const media = page.locator("[data-media]").first();
  await expect(media).toHaveAttribute("data-media", "fallback");
  await expect(media.locator("svg")).toBeVisible();
  await expect(media.locator("img")).toHaveCount(0);
});


test("every offer is openable, not just the cheapest", async ({ page }) => {
  // The whole row is a link: a price you cannot open is not much of an offer,
  // and a supplier with several variants needs each one reachable.
  await page.goto("/en/products/prod-1");
  const offers = page.locator("[data-offers] li a");
  await expect(offers).toHaveCount(2);
  await expect(offers.nth(0)).toHaveAttribute("href", "/en/listings/off-1");
  await expect(offers.nth(1)).toHaveAttribute("href", "/en/listings/off-2");

  await offers.nth(1).click();
  await expect(page).toHaveURL("/en/listings/off-2");
});


test("related products are labelled as unfinished", async ({ page }) => {
  // Same category, nearest price is a weak signal; saying so beats implying it
  // works.
  await page.goto("/en/products/prod-1");
  await expect(page.getByText("Related products")).toBeVisible();
  await expect(page.getByText("WIP")).toBeVisible();
});
