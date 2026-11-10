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
  await expect(page.locator("pre")).toHaveText("User-agent: makhzanbot\nDisallow: /");
  // Truthful during the move: not every request says makhzanbot yet.
  await expect(page.getByText("one shop at a time")).toBeVisible();
});
