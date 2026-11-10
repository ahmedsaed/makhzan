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
  await expect(page.getByText("Our robots.txt token is makhzanbot")).toBeVisible();
  await expect(page.locator("pre").filter({ hasText: "Disallow" })).toHaveText(
    "User-agent: makhzanbot\nDisallow: /",
  );
  // Truthful during the move: not every request says makhzanbot yet.
  await expect(page.getByText("one shop at a time")).toBeVisible();
});

test("how-we-crawl says how to recognise and verify us, on the public origin", async ({
  page,
}) => {
  await page.goto("/how-we-crawl");
  // SITE_URL (playwright.config.ts), filled in at request time: the User-Agent
  // a moved shop sees names this page there, never the copy's placeholder.
  const origin = "https://makhzan.test";
  await expect(page.locator("pre").filter({ hasText: "makhzanbot/1.0" })).toHaveText(
    `makhzanbot/1.0 (+${origin}/how-we-crawl; crawler@makhzan.merope.dev)`,
  );
  await expect(page.getByText(`${origin}${PATH}`)).toBeVisible();
  // The signature is the proof; no address is published (the IPs are shared).
  await expect(page.getByText("45.95.173.97")).toHaveCount(0);
  await expect(page.getByText("{site}")).toHaveCount(0);
  // What we keep, and the promises a shop can hold us to.
  await expect(page.getByText("we do not use shop content to train AI models")).toBeVisible();
  await expect(page.getByText("we do not copy them")).toBeVisible();
  await expect(page.getByText("we will stop, keeping only the name, price")).toBeVisible();
});
