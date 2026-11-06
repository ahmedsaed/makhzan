import { expect, test } from "@playwright/test";

/** The page every result opens. */

test("offers come before related products in the document", async ({ page }) => {
  // That DOM order is what puts the offers first on a phone.
  await page.goto("/products/prod-1");
  const html = (await page.content()).replace(/\s+/g, " ");
  const offers = html.indexOf("data-offers");
  const similar = html.indexOf("Related products");
  expect(offers).toBeGreaterThan(-1);
  expect(similar).toBeGreaterThan(offers);
});

test("an offer with no price stays visible and is not shown as free", async ({ page }) => {
  await page.goto("/products/prod-1");
  await expect(page.getByText("Price on request")).toBeVisible();
  await expect(page.getByText(/EGP\s*0(\.00)?\b/)).toHaveCount(0);
});

test("a range reads 'EGP 185 – 210'", async ({ page }) => {
  await page.goto("/products/prod-1");
  await expect(page.locator("h1 ~ [data-price]")).toHaveText("EGP 185 – 210");
});

test("the hand-off is tagged, opens a new tab and is counted (P4)", async ({ page }) => {
  await page.goto("/products/prod-1");
  const handoff = page.getByRole("link", { name: "View at Shop A" });
  await expect(handoff).toHaveAttribute("href", "https://shop-a.test/p/esp32?ref=makhzan");
  await expect(handoff).toHaveAttribute("target", "_blank");
  await expect(handoff).toHaveAttribute("rel", "noopener");
  await expect(handoff).toHaveAttribute("data-umami-event", "shop-click");
  await expect(handoff).toHaveAttribute("data-umami-event-shop", "shop-a");
});

test("every link out of makhzan carries ref=makhzan", async ({ page }) => {
  for (const path of ["/products/prod-1", "/shops/shop-a"]) {
    await page.goto(path);
    const external = await page
      .locator('a[href^="http"]:not([href^="https://merope.dev"])')
      .evaluateAll((links) => links.map((a) => a.getAttribute("href")));
    expect(external.length, path).toBeGreaterThan(0);
    for (const href of external) expect(href, path).toContain("ref=makhzan");
  }
});

test("a stale price says so, in plain words", async ({ page }) => {
  // The stub's check date is months before today.
  await page.goto("/products/prod-1");
  // Matched on the production build's text, not only in the unit test: the two
  // JSX compilers once disagreed about the space before the day count.
  await expect(page.getByRole("note")).toHaveText(
    /^Price may be out of date\. Last checked \d+ days ago\. Confirm it on the shop's page\.$/,
  );
});

test("a missing product is a real 404", async ({ page }) => {
  const response = await page.goto("/products/does-not-exist");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
});

test("a product with no photo shows the fallback in a white frame", async ({ page }) => {
  await page.goto("/products/prod-1");
  const media = page.locator("[data-media]").first();
  await expect(media).toHaveAttribute("data-media", "fallback");
  await expect(media.locator("svg")).toBeVisible();
  await expect(media.locator("img")).toHaveCount(0);
  await expect(media).toHaveCSS("background-color", "rgb(255, 255, 255)");
});

test("the photo frame stays white in the dark theme (S5)", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/products/prod-1");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("[data-media]").first()).toHaveCSS(
    "background-color",
    "rgb(255, 255, 255)",
  );
});

test("related products open product pages, never a shop (P1)", async ({ page }) => {
  await page.goto("/products/prod-1");
  await expect(page.getByText("WIP")).toBeVisible();
  const hrefs = await page
    .locator("[data-result] a")
    .evaluateAll((links) => links.map((a) => a.getAttribute("href")));
  expect(hrefs).toEqual(["/products/prod-2"]);
});
