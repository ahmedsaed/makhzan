import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * The brand and the layer around the pages: the logo, the icons and the
 * manifest, the sitemap and robots.txt, and the link-preview cards. Stub data
 * (tests/e2e/stub-api.mjs); SITE_URL is https://makhzan.test
 * (playwright.config.ts).
 */

const SITE = "https://makhzan.test";

test("the header carries the logo, named as the way home", async ({ page }) => {
  await page.goto("/trades");
  const home = page.locator("header").getByRole("link", { name: "makhzan, home" });
  await expect(home).toBeVisible();
  await expect(home.locator("[data-logo] svg")).toBeVisible();
  await expect(home).toContainText("makhzan");
  await home.click();
  await expect(page).toHaveURL("/");
  await expect(page.locator("header [data-logo]")).toBeVisible();
});

test("the icons, the manifest, the sitemap and robots.txt respond", async ({ request }) => {
  const svg = await request.get("/icon.svg");
  expect(svg.status()).toBe(200);
  expect(svg.headers()["content-type"]).toContain("image/svg+xml");
  expect(await svg.text()).toContain("prefers-color-scheme: dark");

  for (const path of ["/icon.png", "/apple-icon.png", "/icon-192.png", "/icon-512.png"]) {
    const res = await request.get(path);
    expect(res.status(), path).toBe(200);
    expect(res.headers()["content-type"], path).toBe("image/png");
  }
  expect((await request.get("/favicon.ico")).status()).toBe(200);

  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.status()).toBe(200);
  const body = await manifest.json();
  expect(body.name).toBe("makhzan");
  expect(body.icons.map((icon: { sizes: string }) => icon.sizes)).toEqual(
    expect.arrayContaining(["192x192", "512x512"]),
  );

  const sitemap = await request.get("/sitemap.xml");
  expect(sitemap.status()).toBe(200);
  const xml = await sitemap.text();
  for (const path of ["/", "/trades", "/trades/electronics", "/trades/electronics/ics"]) {
    expect(xml, path).toContain(`<loc>${SITE}${path === "/" ? "" : path}`);
  }
  expect(xml).toContain(`<loc>${SITE}/shops/shop-a</loc>`);
  expect(xml).toContain(`<loc>${SITE}/how-we-crawl</loc>`);
  // A shop with nothing listed is not a page worth sending a crawler to.
  expect(xml).not.toContain("/shops/gone-shop");

  const robots = await request.get("/robots.txt");
  expect(robots.status()).toBe(200);
  const text = await robots.text();
  expect(text).toContain("Disallow: /search");
  expect(text).toContain(`Sitemap: ${SITE}/sitemap.xml`);
});

test("the head links the icons and the manifest", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator('link[rel="icon"][type="image/svg+xml"]')).toHaveCount(1);
  await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveCount(1);
  await expect(page.locator('link[rel="manifest"]')).toHaveCount(1);
});

/** The `content` of a meta tag, by property or name. */
async function meta(page: import("@playwright/test").Page, key: string) {
  return page
    .locator(`meta[property="${key}"], meta[name="${key}"]`)
    .first()
    .getAttribute("content");
}

/** Fetch a card from the page's own og:image, on the test server rather
 *  than SITE_URL, and check it is a PNG. */
async function expectCard(request: APIRequestContext, ogImage: string) {
  const { pathname, search } = new URL(ogImage);
  const res = await request.get(pathname + search);
  expect(res.status(), pathname).toBe(200);
  expect(res.headers()["content-type"]).toBe("image/png");
  const png = await res.body();
  // The PNG signature, and the card's size from the IHDR chunk.
  expect(png.subarray(1, 4).toString()).toBe("PNG");
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([1200, 630]);
}

test("a product page's preview tags are absolute, on SITE_URL", async ({ page, request }) => {
  await page.goto("/products/p-multi");
  expect(await meta(page, "og:title")).toBe("ESP32 Development Board 30 pin · makhzan");
  const description = await meta(page, "og:description");
  expect(description).toContain("EGP 260 – 295");
  expect(description).toContain("at 2 shops");
  expect(await meta(page, "og:url")).toBe(`${SITE}/products/p-multi`);
  expect(await meta(page, "og:site_name")).toBe("makhzan");
  expect(await meta(page, "twitter:card")).toBe("summary_large_image");

  const image = await meta(page, "og:image");
  expect(image).toMatch(new RegExp(`^${SITE}/products/p-multi/opengraph-image`));
  await expectCard(request, image!);
});

test("a product card renders with its photo, and without one it cannot get", async ({
  page,
  request,
}) => {
  for (const id of ["p-photo", "p-photo-missing", "p-photo-garbage"]) {
    await page.goto(`/products/${id}`);
    const image = await meta(page, "og:image");
    expect(image, id).toMatch(new RegExp(`^${SITE}/products/${id}/opengraph-image`));
    await expectCard(request, image!);
  }
});

test("every kind of page has a card, and search is not indexed", async ({ page, request }) => {
  for (const path of ["/", "/trades/electronics", "/trades/electronics/ics", "/shops/shop-a"]) {
    await page.goto(path);
    const image = await meta(page, "og:image");
    expect(image, path).toMatch(new RegExp(`^${SITE}/`));
    await expectCard(request, image!);
  }

  // Pages without a card of their own carry the site's.
  await page.goto("/how-we-crawl");
  expect(await meta(page, "og:image")).toMatch(new RegExp(`^${SITE}/opengraph-image`));

  await page.goto("/search?q=esp32");
  expect(await meta(page, "robots")).toBe("noindex, follow");
  expect(await meta(page, "og:image")).toMatch(new RegExp(`^${SITE}/opengraph-image`));
});

test("the home page describes the site to search engines", async ({ page }) => {
  await page.goto("/");
  const blocks = await page.locator('script[type="application/ld+json"]').allTextContents();
  const data = blocks.flatMap((text) => JSON.parse(text));
  const site = data.find((item: { "@type": string }) => item["@type"] === "WebSite");
  expect(site.url).toBe(`${SITE}/`);
  expect(site.potentialAction.target.urlTemplate).toBe(`${SITE}/search?q={search_term_string}`);
  expect(data.some((item: { "@type": string }) => item["@type"] === "Organization")).toBe(true);
  expect(await meta(page, "description")).toContain("57,207 products from 8 shops");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute("href", SITE);
});
