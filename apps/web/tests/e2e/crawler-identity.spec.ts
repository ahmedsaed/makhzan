import { expect, test } from "@playwright/test";

/**
 * What lets a shop recognise, verify and block our crawler.
 *
 * The Web Bot Auth key directory lives on the public site, at the address our
 * `Signature-Agent` header names, but is served by the API. A verifier
 * (Cloudflare, Shopify) requires a plain 200 there: a redirect fails
 * verification. So the web app must proxy it — a rewrite, never a redirect —
 * and pass the media type and the response's own signature through unchanged.
 */
const PATH = "/.well-known/http-message-signatures-directory";

test("the key directory is proxied with a plain 200, never redirected", async ({ request }) => {
  const response = await request.get(PATH, { maxRedirects: 0 });
  expect(response.status()).toBe(200);
  const headers = response.headers();
  expect(headers["content-type"]).toBe("application/http-message-signatures-directory+json");
  expect(headers["signature-input"]).toContain('tag="http-message-signatures-directory"');
  expect(headers.signature).toBe("sig1=:c3R1Yg==:");
  expect(await response.json()).toEqual({ keys: [{ kty: "OKP", crv: "Ed25519", x: "stub" }] });
});

test("how-we-crawl names our robots.txt token and gives the block to copy", async ({ page }) => {
  await page.goto("/how-we-crawl");
  await page.getByRole("tab", { name: "robots.txt" }).click();
  await expect(page.getByText("Our robots.txt token is makhzanbot")).toBeVisible();
  await expect(page.locator("#block pre")).toHaveText("User-agent: makhzanbot\nDisallow: /");
  // Truthful during the move: not every request says makhzanbot yet.
  await expect(page.getByText("one shop at a time")).toBeVisible();
});

test("how-we-crawl says how to recognise and verify us, on the public origin", async ({ page }) => {
  await page.goto("/how-we-crawl");
  // SITE_URL (playwright.config.ts), filled in at request time: the User-Agent
  // a moved shop sees names this page there, never the copy's placeholder.
  const origin = "https://makhzan.test";
  const userAgent = `makhzanbot/1.0 (+${origin}/how-we-crawl; crawler@makhzan.merope.dev)`;
  await expect(page.locator("#panel-user-agent pre")).toHaveText(userAgent);
  await expect(
    page.getByRole("figure", { name: "What a request from makhzanbot looks like" }),
  ).toBeVisible();
  // The annotated request: the User-Agent, the From header and the signature
  // headers, the Signature-Agent naming our own origin.
  const request = page.locator("[data-example-request]");
  await expect(request).toContainText(`User-Agent: ${userAgent}`);
  await expect(request).toContainText("From: crawler@makhzan.merope.dev");
  await expect(request).toContainText(`Signature-Agent: "${origin}"`);
  await expect(request).toContainText('tag="web-bot-auth"');

  await page.getByRole("tab", { name: "Web Bot Auth" }).click();
  await expect(page.getByText(`${origin}${PATH}`)).toBeVisible();
  // The signature is the proof; no address is published (the IPs are shared).
  await expect(page.getByText("45.95.173.97")).toHaveCount(0);
  await expect(page.getByText("{site}")).toHaveCount(0);
  // What we keep, and the promises a shop can hold us to.
  await expect(page.getByText("use shop content to train AI models")).toBeVisible();
  await expect(page.getByText("copy photos", { exact: true })).toBeVisible();
  await expect(page.getByText("we will stop, keeping only the name, price")).toBeVisible();
});

test("how-we-crawl does not mention Cloudflare", async ({ page }) => {
  // Not until the verified-bots registration is settled.
  await page.goto("/how-we-crawl");
  expect(await page.locator("body").innerHTML()).not.toMatch(/cloudflare/i);
});

test("the identification tabs: one panel at a time, arrow keys between them", async ({ page }) => {
  await page.goto("/how-we-crawl");
  const tabs = page.getByRole("tablist", { name: "Ways to identify makhzanbot" });
  await expect(tabs.getByRole("tab")).toHaveText(["User-Agent", "robots.txt", "Web Bot Auth"]);
  await expect(page.getByRole("tabpanel")).toHaveCount(1);
  await expect(page.getByRole("tabpanel")).toContainText("To search your logs for it");

  await tabs.getByRole("tab", { name: "User-Agent" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "robots.txt" })).toBeFocused();
  await expect(tabs.getByRole("tab", { name: "robots.txt" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("tabpanel")).toContainText("Our robots.txt token is makhzanbot");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(tabs.getByRole("tab", { name: "Web Bot Auth" })).toBeFocused();
});

test("without JavaScript every panel shows and nothing pretends to copy", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/how-we-crawl");
  await expect(page.getByRole("tablist")).toHaveCount(0);
  for (const heading of ["User-Agent", "robots.txt", "Web Bot Auth"]) {
    await expect(page.getByRole("heading", { level: 3, name: heading, exact: true })).toBeVisible();
  }
  await expect(page.getByText("Our robots.txt token is makhzanbot")).toBeVisible();
  await expect(page.getByText(`https://makhzan.test${PATH}`)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Copy/ })).toHaveCount(0);
  // The questions open without it too: they are <details>.
  await page.getByText("How do I stop makhzanbot reading my site?").click();
  await expect(page.getByRole("link", { name: "The two lines →" })).toBeVisible();
  await context.close();
});

test("with JavaScript each snippet gets a copy button that says what it copies", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/how-we-crawl");
  await expect(page.getByRole("button", { name: "Copy User-Agent", exact: true })).toBeVisible();
  for (const tab of ["robots.txt", "Web Bot Auth"]) {
    await page.getByRole("tab", { name: tab }).click();
  }
  await expect(page.getByRole("button", { name: "Copy key directory URL" })).toBeVisible();
  await page.getByRole("tab", { name: "robots.txt" }).click();
  await expect(page.getByRole("button", { name: "Copy robots.txt token" })).toBeVisible();

  const copy = page.getByRole("button", { name: "Copy robots.txt block" });
  await copy.click();
  // The outcome is announced by a status beside the button; the button keeps its name.
  await expect(page.locator("#block").getByRole("status")).toHaveText("Copied robots.txt block");
  await expect(copy).toHaveAccessibleName("Copy robots.txt block");
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "User-agent: makhzanbot\nDisallow: /",
  );
});
