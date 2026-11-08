import { expect, test } from "@playwright/test";

/**
 * The page every result opens. Products are the stub's fixtures
 * (tests/e2e/fixtures/product.mjs): `p-single` has one offer checked 74 days
 * ago, `p-multi` five in stock and two out, `p-oos` three, all out of stock.
 */

const PHONE = { width: 390, height: 844 };

test.describe("one offer", () => {
  test.use({ viewport: PHONE });

  test("a phone keeps the price, its age and the way out in a bottom bar", async ({ page }) => {
    await page.goto("/products/p-single");
    const bar = page.locator("[data-bottom-bar]");
    await expect(bar).toBeVisible();
    await expect(bar.locator("[data-price]")).toHaveText("EGP 850");
    await expect(bar).toContainText("checked 74 days ago");
    const handoff = bar.getByRole("link", { name: "View at Volt Corner" });
    await expect(handoff).toHaveAttribute(
      "href",
      "https://volt-corner.test/p/o-single?variant=1&ref=makhzan",
    );
    await expect(handoff).toHaveAttribute("target", "_blank");
    await expect(handoff).toHaveAttribute("data-umami-event", "shop-click");
    await expect(handoff).toHaveAttribute("data-umami-event-shop", "volt-corner");
  });

  test("the bar never covers the end of the page", async ({ page }) => {
    await page.goto("/products/p-single");
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const bar = await page.locator("[data-bottom-bar]").boundingBox();
    const footer = await page.locator("footer").boundingBox();
    expect(bar && footer).toBeTruthy();
    expect(footer!.y + footer!.height).toBeLessThanOrEqual(bar!.y + 1);
  });

  test("states price, stock and the shop, with a card to the shop's page", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.locator("[data-stock]")).toHaveText("In stock at Volt Corner");
    await expect(page.getByText("DC-150")).toHaveAttribute("data-identifier");
    const soldBy = page.locator("[data-sold-by]");
    await expect(soldBy).toHaveAttribute("href", "/shops/volt-corner");
    await expect(soldBy).toContainText("Sold by");
    await expect(soldBy).toContainText("4,340 products · search this shop");
    // One offer is not a comparison (P2).
    await expect(page.locator("[data-offer]")).toHaveCount(0);
  });

  test("an old price says so, in plain words", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.getByRole("note")).toHaveText(
      "Price may be out of date. Last checked 74 days ago. Confirm it on the shop's page.",
    );
  });

  test("shows a count on each photo when there are several", async ({ page }) => {
    await page.goto("/products/p-single");
    const gallery = page.locator("[data-gallery]");
    await expect(gallery.locator("[data-media]")).toHaveCount(2);
    await expect(gallery).toContainText("1 / 2");
  });

  test("similar products open product pages, never a shop (P1)", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.getByRole("heading", { name: "Similar products" })).toBeVisible();
    const hrefs = await page
      .locator("[data-result] a")
      .evaluateAll((links) => links.map((a) => a.getAttribute("href")));
    expect(hrefs).toEqual(["/products/p-oos", "/products/p-similar-2"]);
  });
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false, viewport: PHONE });

  test("the description's Read more opens", async ({ page }) => {
    await page.goto("/products/p-single");
    const text = page.locator("[data-description] p");
    const clamped = (await text.boundingBox())!.height;
    await page.getByText("Read more").click();
    await expect(page.getByText("Show less")).toBeVisible();
    expect((await text.boundingBox())!.height).toBeGreaterThan(clamped);
  });

  test("the out-of-stock offers unfold", async ({ page }) => {
    await page.goto("/products/p-multi");
    const folded = page.locator("[data-out-of-stock] [data-offer]");
    await expect(folded.first()).toBeHidden();
    await page.getByText("Show 2 out of stock offers").click();
    await expect(folded).toHaveCount(2);
    await expect(folded.first()).toBeVisible();
    await expect(folded.locator("[data-offer-title]")).toHaveText([
      "ESP32 DevKit 30 pin, old stock",
      "ESP32 38 pin board",
    ]);
  });
});

test.describe("several offers", () => {
  test("summarises what is in stock, where, and for how much", async ({ page }) => {
    await page.goto("/products/p-multi");
    const summary = page.locator("[data-summary]");
    await expect(summary).toContainText("5 offers in stock at 2 shops");
    await expect(summary.locator("[data-price]")).toHaveText("EGP 260 – 295");
    await expect(summary.getByRole("link", { name: "EGP 260 at Delta Bench" })).toBeVisible();
    await expect(page.getByText("Each offer shows the shop's own title.")).toBeVisible();
  });

  test("lists in-stock offers lowest price first, each led by its own title", async ({ page }) => {
    await page.goto("/products/p-multi");
    const rows = page.locator("section[aria-labelledby=offers-heading] > div > ul [data-offer]");
    await expect(rows.locator("[data-price]")).toHaveText([
      "EGP 260",
      "EGP 270",
      "EGP 280",
      "EGP 290",
      "EGP 295",
    ]);
    await expect(rows.locator("[data-offer-title]")).toHaveText([
      "ESP32 Development Board 30 pin (WIFI - Bluetooth)",
      "ESP32 Development Board 30-Pin with CP2102 Type-C",
      "ESP32 Development Board 30-Pin with CP2102",
      "ESP32S ESP-WROOM-32 38-Pin CP2102",
      "ESP32 Development Board 38-Pin – Micro USB",
    ]);
    // Each row carries its own shop, freshness and link (P3).
    for (const row of await rows.all()) {
      await expect(row.locator("a[href^='/shops/']")).toHaveCount(1);
      await expect(row.locator("[data-freshness]")).toHaveCount(1);
      await expect(row.getByRole("link", { name: /^View at / })).toHaveCount(1);
    }
  });

  test("on a phone, the bar points at the cheapest in-stock offer", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-multi");
    const bar = page.locator("[data-bottom-bar]");
    await expect(bar.locator("[data-price]")).toHaveText("EGP 260");
    await expect(bar.getByRole("link", { name: "View at Delta Bench" })).toBeVisible();
  });

  test("a wide screen has no bottom bar", async ({ page }) => {
    await page.goto("/products/p-multi");
    await expect(page.locator("[data-bottom-bar]")).toBeHidden();
  });
});

test.describe("every offer out of stock", () => {
  test("says so, still lists them, and opens the most recently checked", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-oos");
    await expect(page.locator("[data-summary]")).toContainText("Out of stock at all 3 shops");
    await expect(page.locator("[data-offer]")).toHaveCount(3);
    await expect(page.locator("[data-out-of-stock]")).toHaveCount(0);
    await expect(
      page.locator("[data-bottom-bar]").getByRole("link", { name: "View at Nile Parts" }),
    ).toBeVisible();
  });
});

test("the head names the product and describes it to search engines", async ({ page }) => {
  await page.goto("/products/p-multi");
  await expect(page).toHaveTitle("ESP32 Development Board 30 pin · makhzan");
  await expect(page.locator('meta[name="description"]')).toHaveAttribute(
    "content",
    /EGP 260 – 295 at 2 shops/,
  );
  const data = JSON.parse(
    (await page.locator('script[type="application/ld+json"]').textContent()) ?? "{}",
  );
  expect(data["@type"]).toBe("Product");
  expect(data.offers).toMatchObject({
    "@type": "AggregateOffer",
    priceCurrency: "EGP",
    lowPrice: 240,
    highPrice: 300,
    offerCount: 7,
  });
  // Absolute, on the configured SITE_URL (playwright.config.ts), never on the
  // host the request happened to name.
  expect(data.offers.url).toBe("https://makhzan.test/products/p-multi");
  // A comparison, not a shop: no Offer, so Google does not ask for shipping.
  expect(JSON.stringify(data)).not.toContain('"@type":"Offer"');
  expect(data.description).toBeTruthy();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    "https://makhzan.test/products/p-multi",
  );
});

test("a static page's canonical is on SITE_URL too", async ({ page }) => {
  await page.goto("/how-we-crawl");
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    "https://makhzan.test/how-we-crawl",
  );
});

test("the breadcrumb walks trade › group › category, all links", async ({ page }) => {
  await page.goto("/products/p-single");
  const crumbs = page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link");
  await expect(crumbs).toHaveText(["Electronics", "Components", "Integrated Circuits"]);
  await expect(crumbs.last()).toHaveAttribute("href", "/trades/electronics/ics");
});

test("an offer with no price stays visible and is not shown as free", async ({ page }) => {
  await page.goto("/products/prod-1");
  await expect(page.locator("[data-offer]").getByText("Price on request")).toBeVisible();
  await expect(page.getByText(/EGP\s*0(\.00)?\b/)).toHaveCount(0);
});

test.describe("what the shop published (C4)", () => {
  test("specs, datasheets and brand, each labelled with its source", async ({ page }) => {
    await page.goto("/products/p-specs");
    await expect(page.locator("[data-brand]")).toHaveText("Brand · UNI-T");

    const specs = page.locator("[data-specs]");
    await expect(specs.getByRole("heading", { name: "Specifications" })).toBeVisible();
    await expect(specs).toContainText("From Nile Parts's listing");
    await expect(specs.locator("dt")).toHaveText(["Model", "DC Voltage", "Display"]);
    await expect(specs.locator("dd")).toHaveText(["UT61E", "220mV – 1000V", "22000 counts"]);
    // Monospace only where the value is a part number (S3).
    await expect(specs.locator("[data-identifier]")).toHaveText(["UT61E"]);

    const sheets = page.locator("[data-datasheets]");
    await expect(sheets.getByRole("heading", { name: "Datasheets" })).toBeVisible();
    await expect(sheets).toContainText("From Nile Parts's listing");
    const links = sheets.locator("[data-datasheet]");
    await expect(links).toHaveText(["UT61E user manual", "ut61e-datasheet.pdf"]);
    // Each opens the file on the shop's site, through the one way out (P4).
    await expect(links.first()).toHaveAttribute(
      "href",
      "https://nile-parts.test/files/ut61e-manual.pdf?ref=makhzan",
    );
    await expect(links.last()).toHaveAttribute(
      "href",
      "https://nile-parts.test/files/ut61e-datasheet.pdf?ref=makhzan",
    );
    await expect(links.first()).toHaveAttribute("target", "_blank");
    await expect(links.first().locator("svg")).toHaveCount(1);
  });

  test("a wide screen gives them the wide column, beside the photo and price", async ({ page }) => {
    await page.goto("/products/p-specs");
    const description = (await page.locator("[data-description]").boundingBox())!;
    const specs = (await page.locator("[data-specs]").boundingBox())!;
    const photo = (await page.locator("[data-gallery]").boundingBox())!;
    const buy = (await page.locator("[data-buy]").boundingBox())!;
    expect(specs.y).toBeGreaterThan(description.y + description.height - 1);
    expect(specs.x).toBeCloseTo(description.x, 0);
    // The narrow column holds the photo and the way to the shop; the text is
    // to its right and wider than it.
    expect(specs.x).toBeGreaterThan(photo.x + photo.width);
    expect(buy.x).toBeCloseTo(photo.x, 0);
    expect(buy.y).toBeGreaterThan(photo.y + photo.height - 1);
    expect(specs.width).toBeGreaterThan(photo.width);
  });

  test("a phone shows them after the description", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-specs");
    const description = (await page.locator("[data-description]").boundingBox())!;
    const specs = (await page.locator("[data-specs]").boundingBox())!;
    const sheets = (await page.locator("[data-datasheets]").boundingBox())!;
    expect(specs.y).toBeGreaterThan(description.y + description.height - 1);
    expect(sheets.y).toBeGreaterThan(specs.y + specs.height - 1);
  });

  test("a product whose shop published none has no section, not an empty one", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.locator("[data-description]")).toBeVisible();
    await expect(page.locator("[data-specs]")).toHaveCount(0);
    await expect(page.locator("[data-datasheets]")).toHaveCount(0);
    await expect(page.locator("[data-brand]")).toHaveCount(0);
    await expect(page.locator("dl, table")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Specifications" })).toHaveCount(0);
  });

  test("several shops: a tab per shop that wrote something, richest first", async ({ page }) => {
    await page.goto("/products/p-multi");
    const tabs = page.locator("[data-details-tab]");
    await expect(tabs).toHaveText(["Delta Bench", "Nile Parts"]);
    const specs = page.locator("[data-specs]:visible");
    await expect(specs).toHaveCount(1);
    await expect(specs).toContainText("From Delta Bench's listing");
    await expect(specs.locator("dt")).toHaveText(["Flash Memory", "GPIO Pins"]);
    await expect(page.getByText("USB Chip")).toBeHidden();

    await tabs.filter({ hasText: "Nile Parts" }).click();
    await expect(specs).toContainText("From Nile Parts's listing");
    await expect(specs.locator("dt")).toHaveText(["USB Chip"]);
    await expect(page.locator("[data-datasheets]")).toHaveCount(0);
  });

  test.describe("without JavaScript", () => {
    test.use({ javaScriptEnabled: false });

    test("the shop tabs still switch", async ({ page }) => {
      await page.goto("/products/p-multi");
      await page.locator("[data-details-tab]", { hasText: "Nile Parts" }).click();
      await expect(page.locator("[data-specs]:visible dt")).toHaveText(["USB Chip"]);
    });
  });
});

test.describe("full-size photos", () => {
  // 1x1 PNG: enough for the browser to decode and fire `load`.
  const PIXEL = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64",
  );
  const MEDIA = "https://media.nile-parts.test/uploads";
  const THUMB = (stem: string) => `${MEDIA}/cache/2025-01-10/product/image/${stem}-q-80-h-150.webp`;

  /** The front photo's original is a .png (the .jpeg guess 404s); the back's
   *  original is gone altogether. Returns every URL the browser asked for. */
  async function serveMedia(page: import("@playwright/test").Page): Promise<string[]> {
    const requested: string[] = [];
    await page.route(`${MEDIA}/**`, (route) => {
      const url = route.request().url();
      requested.push(url);
      const found = url.endsWith("-q-80-h-150.webp") || url.endsWith("/ut61e-front.png");
      return found
        ? route.fulfill({ status: 200, contentType: "image/png", body: PIXEL })
        : route.fulfill({ status: 404, contentType: "text/plain", body: "not found" });
    });
    return requested;
  }

  test("the gallery swaps in the original, and keeps the thumbnail when there is none", async ({
    page,
  }) => {
    const requested = await serveMedia(page);
    await page.goto("/products/p-specs");
    const photos = page.locator("[data-gallery] img");
    await expect(photos.first()).toHaveAttribute(
      "src",
      `${MEDIA}/2025-01-10/product/image/ut61e-front.png`,
    );
    await expect(photos.nth(1)).toHaveAttribute("src", THUMB("ut61e-back"));
    // .jpeg is tried first, then .png; a failed guess never shows as broken.
    const front = requested.filter((url) => url.includes("/image/ut61e-front."));
    expect(front).toEqual([
      `${MEDIA}/2025-01-10/product/image/ut61e-front.jpeg`,
      `${MEDIA}/2025-01-10/product/image/ut61e-front.png`,
    ]);
    await expect(page.locator("[data-gallery] [data-media]").first()).toHaveAttribute(
      "data-media",
      "photo",
    );
  });

  test("an original is fetched only once its photo is on screen", async ({ page }) => {
    // Each original costs the shop bandwidth: the second photo's is not asked
    // for until the strip is swiped to it.
    const requested = await serveMedia(page);
    await page.goto("/products/p-specs");
    const photos = page.locator("[data-gallery] img");
    await expect(photos.first()).toHaveAttribute("src", /ut61e-front\.png$/);
    const back = () => requested.filter((url) => url.includes("/image/ut61e-back."));
    expect(back()).toEqual([]);

    await photos.nth(1).scrollIntoViewIfNeeded();
    await expect
      .poll(back)
      .toEqual([
        `${MEDIA}/2025-01-10/product/image/ut61e-back.jpeg`,
        `${MEDIA}/2025-01-10/product/image/ut61e-back.png`,
      ]);
  });

  test.describe("without JavaScript", () => {
    test.use({ javaScriptEnabled: false });

    test("the thumbnail is still there", async ({ page }) => {
      await serveMedia(page);
      await page.goto("/products/p-specs");
      await expect(page.locator("[data-gallery] img")).toHaveCount(2);
      await expect(page.locator("[data-gallery] img").first()).toHaveAttribute(
        "src",
        THUMB("ut61e-front"),
      );
    });
  });
});

test("every link out of makhzan carries ref=makhzan (P4)", async ({ page }) => {
  for (const path of [
    "/products/p-specs",
    "/products/p-single",
    "/products/p-multi",
    "/products/p-oos",
    "/shops/shop-a",
  ]) {
    await page.goto(path);
    const external = await page
      .locator('a[href^="http"]:not([href^="https://merope.dev"])')
      .evaluateAll((links) => links.map((a) => a.getAttribute("href")));
    expect(external.length, path).toBeGreaterThan(0);
    for (const href of external) expect(href, path).toContain("ref=makhzan");
  }
});

test("nothing scrolls sideways at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  for (const path of ["/products/p-single", "/products/p-multi", "/products/p-oos"]) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("a missing product is a real 404, with search and a way home", async ({ page }) => {
  const response = await page.goto("/products/does-not-exist");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await expect(page.locator("main").getByRole("search")).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to the home page" })).toHaveAttribute(
    "href",
    "/",
  );
});

test("a malformed id is a 404 too, not an error page", async ({ page }) => {
  // The API answers 422 for an id that is not a UUID.
  const response = await page.goto("/products/malformed-id");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
});

test("a product with no photo shows the fallback in a white frame", async ({ page }) => {
  await page.goto("/products/prod-1");
  const media = page.locator("[data-media]:visible").first();
  await expect(media).toHaveAttribute("data-media", "fallback");
  await expect(media.locator("svg")).toBeVisible();
  await expect(media.locator("img")).toHaveCount(0);
  await expect(media).toHaveCSS("background-color", "rgb(255, 255, 255)");
});

test("the photo frame stays white in the dark theme (S5)", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/products/prod-1");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.locator("[data-media]:visible").first()).toHaveCSS(
    "background-color",
    "rgb(255, 255, 255)",
  );
});

test.describe("a product id a regroup replaced", () => {
  test("redirects permanently to where its offers went", async ({ page }) => {
    const response = await page.request.get("/products/p-replaced", { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(response.headers()["location"]).toMatch(/\/products\/p-multi$/);

    await page.goto("/products/p-replaced");
    await expect(page).toHaveURL(/\/products\/p-multi$/);
    await expect(page.locator("h1")).toHaveText("ESP32 Development Board 30 pin");
  });

  test("an id with nowhere to go is still a 404", async ({ page }) => {
    const response = await page.goto("/products/p-never-existed");
    expect(response?.status()).toBe(404);
  });
});
