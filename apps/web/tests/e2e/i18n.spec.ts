import { expect, test } from "@playwright/test";

/**
 * Language is the thing the rewrite existed to fix. Before it, `<html lang>` was
 * always "en" on the server, an Arabic page had no URL, and the choice reset on
 * reload. Each of those is asserted here rather than assumed.
 */

test("a bare path is redirected to a language", async ({ page }) => {
  const response = await page.goto("/");
  expect(new URL(page.url()).pathname).toBe("/en");
  expect(response?.status()).toBe(200);
});

test("an Arabic browser lands on Arabic", async ({ browser }) => {
  const context = await browser.newContext({ locale: "ar-EG", extraHTTPHeaders: { "accept-language": "ar-EG,ar;q=0.9" } });
  const page = await context.newPage();
  await page.goto("/");
  expect(new URL(page.url()).pathname).toBe("/ar");
  await context.close();
});

test("direction and language come from the server, not an effect", async ({ page }) => {
  await page.goto("/ar");
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  await page.goto("/en");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
});

test("the Arabic page is server-rendered, not hydrated into place", async ({ browser }) => {
  // With JavaScript off there is no effect to correct anything, so whatever is
  // here came from the server.
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/ar");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("ابحث");
  await context.close();
});

test("switching language keeps the page and its query", async ({ page }) => {
  await page.goto("/en/search?q=ESP32");
  await page.getByRole("link", { name: /العربية|ع$/ }).first().click();
  await expect(page).toHaveURL(/\/ar\/search\?q=ESP32/);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
});

test("each page declares its other-language twin", async ({ page }) => {
  await page.goto("/en/products/prod-1");
  const alternates = page.locator('link[rel="alternate"]');
  await expect(alternates).toHaveCount(2);
  await expect(page.locator('link[hreflang="ar"]')).toHaveAttribute(
    "href",
    "/ar/products/prod-1",
  );
});

test("a part number stays left-to-right inside Arabic text", async ({ page }) => {
  // Without isolation ESP32-WROOM-32 reorders around its hyphens in an RTL run.
  await page.goto("/ar/products/prod-1");
  const identifier = page.locator("[data-identifier]").first();
  await expect(identifier).toHaveText("ESP32-WROOM-32");
  await expect(identifier).toHaveCSS("direction", "ltr");
});
