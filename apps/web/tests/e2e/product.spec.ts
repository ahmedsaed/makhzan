import { expect, test } from "@playwright/test";

/**
 * The page every result opens. Products are the stub's fixtures
 * (tests/e2e/fixtures/product.mjs): `p-single` has one offer checked 74 days
 * ago, `p-multi` five in stock and two out, `p-oos` three, all out of stock.
 */

const PHONE = { width: 390, height: 844 };

/** The page's JSON-LD block of one `@type`. A page has several (product,
 *  breadcrumbs), and Playwright's text filters skip `<script>` elements. */
async function jsonLd(page: import("@playwright/test").Page, type: string) {
  const blocks = await page
    .locator('script[type="application/ld+json"]')
    .evaluateAll((nodes) => nodes.map((node) => JSON.parse(node.textContent ?? "{}")));
  const found = blocks.find((block) => block["@type"] === type);
  expect(found, `a ${type} block`).toBeTruthy();
  return found;
}

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
    expect(hrefs).toEqual([
      "/products/p-oos",
      "/products/p-similar-2",
      "/products/p-similar-3",
      "/products/p-similar-4",
    ]);
  });
});

test.describe("makhzan's own facts, under the title", () => {
  test("one shop: who sells it and when, and the similar products", async ({ page }) => {
    await page.goto("/products/p-single");
    const facts = page.locator("[data-facts]");
    await expect(facts.locator("[data-fact]")).toHaveText([
      "Sold by 1 shop · checked 74 days ago",
      "4 similar products, from EGP 35",
    ]);
    // The age keeps its F2 colour here too.
    await expect(facts.locator("[data-freshness]")).toHaveAttribute("data-freshness", "warn");
    await facts.getByRole("link", { name: "4 similar products" }).click();
    await expect(page).toHaveURL(/#similar$/);
    await expect(page.getByRole("heading", { name: "Similar products" })).toBeInViewport();
  });

  test("several shops: how many, where in stock, the range", async ({ page }) => {
    await page.goto("/products/p-multi");
    await expect(page.locator("[data-fact=shops]")).toHaveText(
      "Sold by 3 shops · 7 listings · in stock at 2 · EGP 260 – 295",
    );
    await page.goto("/products/p-oos");
    await expect(page.locator("[data-fact=shops]")).toHaveText(
      "Sold by 3 shops · none in stock · EGP 40 – 50",
    );
  });

  test("a fact with nothing behind it is left out, never shown empty", async ({ page }) => {
    await page.goto("/products/p-bare");
    const facts = page.locator("[data-fact]");
    await expect(facts).toHaveCount(1);
    await expect(facts).toHaveText("Sold by 1 shop · checked 2 days ago");
    await expect(page.locator("[data-similar]")).toHaveCount(0);
  });
});

test.describe("what comes first", () => {
  /** Top edges, in the order given: each must start below the one before. */
  async function expectOrder(page: import("@playwright/test").Page, selectors: string[]) {
    const tops: number[] = [];
    for (const selector of selectors) {
      tops.push((await page.locator(selector).first().boundingBox())!.y);
    }
    for (let i = 1; i < tops.length; i++) {
      expect(tops[i], `${selectors[i]} below ${selectors[i - 1]}`).toBeGreaterThan(tops[i - 1]);
    }
  }

  test("a phone, one shop: photo, title, facts, price, the shop's text, similar", async ({
    page,
  }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-single");
    await expectOrder(page, [
      "[data-gallery]",
      "h1",
      "[data-facts]",
      "[data-buy] [data-price]",
      "[data-description]",
      "[data-similar]",
    ]);
  });

  test("a phone, several shops: the offers, then the shops' text, similar last", async ({
    page,
  }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-multi");
    await expectOrder(page, [
      "h1",
      "[data-facts]",
      "[data-summary]",
      "[data-offer]",
      "[data-details]",
      "[data-similar]",
    ]);
  });

  for (const viewport of [PHONE, { width: 1440, height: 900 }]) {
    test(`similar products come last on every kind of page (${viewport.width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      for (const path of ["/products/p-single", "/products/p-multi", "/products/p-specs"]) {
        await page.goto(path);
        const similar = (await page.locator("[data-similar]").boundingBox())!;
        // Everything else in the product's layout ends above it.
        const others = await page
          .locator("[data-buy], [data-details], [data-description], [data-gallery], h1")
          .evaluateAll((nodes) => nodes.map((n) => n.getBoundingClientRect().bottom + scrollY));
        for (const bottom of others) expect(bottom, path).toBeLessThanOrEqual(similar.y + 1);
        // And it spans the page, not one column.
        expect(similar.width, path).toBeGreaterThan(viewport.width * 0.8);
      }
    });
  }

  test("a wide screen, a shop that wrote nothing: price beside the title", async ({ page }) => {
    await page.goto("/products/p-bare");
    const photo = (await page.locator("[data-media]").first().boundingBox())!;
    const buy = (await page.locator("[data-buy]").boundingBox())!;
    expect(buy.x).toBeGreaterThan(photo.x + photo.width);
  });
});

test.describe("photo arrows", () => {
  const scrollOf = (page: import("@playwright/test").Page, selector: string) =>
    page.locator(selector).evaluate((node) => node.scrollLeft);

  test("the gallery's move one photo and are disabled at the ends", async ({ page }) => {
    await page.goto("/products/p-single");
    const previous = page.getByRole("button", { name: "Previous photo" });
    const next = page.getByRole("button", { name: "Next photo" });
    await expect(previous).toBeDisabled();
    await expect(next).toBeEnabled();
    await next.click();
    await expect.poll(() => scrollOf(page, "[data-gallery]")).toBeGreaterThan(100);
    await expect(next).toBeDisabled();
    await expect(previous).toBeEnabled();
    await previous.click();
    await expect.poll(() => scrollOf(page, "[data-gallery]")).toBe(0);
    await expect(previous).toBeDisabled();
  });

  test("one photo has none", async ({ page }) => {
    await page.goto("/products/p-bare");
    await expect(page.locator("a[data-photo]")).toHaveCount(1);
    await expect(page.getByRole("button", { name: /photo$/ })).toHaveCount(0);
  });

  test("a phone's row of similar products has them too", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-single");
    const row = "[data-similar] [data-carousel-track]";
    const previous = page.getByRole("button", { name: "Previous products" });
    const next = page.getByRole("button", { name: "Next products" });
    await expect(previous).toBeDisabled();
    await next.click();
    await expect.poll(() => scrollOf(page, row)).toBeGreaterThan(50);
    await expect(previous).toBeEnabled();
  });

  test("a wide screen's grid of similar products has none", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.getByRole("button", { name: /products$/ })).toHaveCount(0);
  });
});

test.describe("the photo viewer", () => {
  /** Serves Volt Corner's photos (p-single, p-bare): any image will do. */
  async function servePhotos(page: import("@playwright/test").Page) {
    const PNG = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    );
    await page.route("https://volt-corner.test/img/**", (route) =>
      route.fulfill({ status: 200, contentType: "image/png", body: PNG }),
    );
  }

  test("opens on the photo, moves with arrows and keys, closes with Esc", async ({ page }) => {
    await servePhotos(page);
    await page.goto("/products/p-single");
    const viewer = page.locator("dialog[data-viewer]");
    await expect(viewer).toBeHidden();
    await page.locator('[data-gallery] a[data-photo="0"]').click();
    await expect(viewer).toBeVisible();
    const count = viewer.locator("[data-viewer-count]");
    await expect(count).toHaveText("1 / 2");
    // Focus moved into the dialog.
    await expect(viewer.getByRole("button", { name: "Close" })).toBeFocused();
    // The photo keeps its white frame (S5).
    await expect(viewer.locator("[data-media]").first()).toHaveCSS(
      "background-color",
      "rgb(255, 255, 255)",
    );

    await page.keyboard.press("ArrowRight");
    await expect(count).toHaveText("2 / 2");
    await expect(viewer.getByRole("button", { name: "Next photo" })).toBeDisabled();
    await viewer.getByRole("button", { name: "Previous photo" }).click();
    await expect(count).toHaveText("1 / 2");
    await expect(viewer.getByRole("button", { name: "Previous photo" })).toBeDisabled();
    await viewer.getByRole("button", { name: "Next photo" }).click();
    await expect(count).toHaveText("2 / 2");

    await page.keyboard.press("Escape");
    await expect(viewer).toBeHidden();
    // Focus returns to the photo last shown.
    await expect(page.locator('[data-gallery] a[data-photo="1"]')).toBeFocused();
  });

  test("swiping the viewer moves the count; the close button closes it", async ({ page }) => {
    await servePhotos(page);
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-single");
    await page.locator('[data-gallery] a[data-photo="1"]').click({ force: true });
    const viewer = page.locator("dialog[data-viewer]");
    const count = viewer.locator("[data-viewer-count]");
    // It opens on the photo tapped.
    await expect(count).toHaveText("2 / 2");
    // A swipe is a scroll of the strip, as far as the page can tell.
    await viewer
      .locator("[data-viewer-slide]")
      .first()
      .evaluate((slide) => slide.parentElement!.scrollTo({ left: 0 }));
    await expect(count).toHaveText("1 / 2");
    await viewer.getByRole("button", { name: "Close" }).click();
    await expect(viewer).toBeHidden();
    await expect(page.locator('[data-gallery] a[data-photo="0"]')).toBeFocused();
  });

  test("one photo opens too, with no arrows", async ({ page }) => {
    await servePhotos(page);
    await page.goto("/products/p-bare");
    await page.locator("a[data-photo]").click();
    const viewer = page.locator("dialog[data-viewer]");
    await expect(viewer.locator("[data-viewer-count]")).toHaveText("1 / 1");
    await expect(viewer.getByRole("button", { name: /photo$/ })).toHaveCount(0);
  });

  test.describe("without JavaScript", () => {
    test.use({ javaScriptEnabled: false });

    test("each photo is a plain link to the image", async ({ page }) => {
      await page.goto("/products/p-single");
      await expect(page.locator("a[data-photo]")).toHaveCount(2);
      await expect(page.locator('a[data-photo="0"]')).toHaveAttribute(
        "href",
        "https://volt-corner.test/img/caliper-1.jpg?ref=makhzan",
      );
      await expect(page.getByRole("button", { name: /photo$/ })).toHaveCount(0);
    });
  });
});

/** The description's text: how tall it is drawn, and how tall it would be in full. */
const descriptionHeights = (page: import("@playwright/test").Page) =>
  page.locator("[data-description] p").evaluate((node) => ({
    shown: node.clientHeight,
    full: node.scrollHeight,
    line: parseFloat(getComputedStyle(node).lineHeight),
  }));

for (const viewport of [PHONE, { width: 1440, height: 900 }]) {
  test.describe(`a long description at ${viewport.width}px`, () => {
    // p-single's description runs well past 25 lines in either column.
    test.use({ viewport });

    test("is clamped to 25 lines with a fade and Read more, and opens", async ({ page }) => {
      await page.goto("/products/p-single");
      const clamped = await descriptionHeights(page);
      expect(Math.round(clamped.shown / clamped.line)).toBe(25);
      expect(clamped.full).toBeGreaterThan(clamped.shown);
      await expect(page.locator("[data-description-fade]")).toBeVisible();

      await page.getByText("Read more").click();
      await expect(page.getByText("Show less")).toBeVisible();
      const open = await descriptionHeights(page);
      expect(open.shown).toBeGreaterThanOrEqual(open.full - 1);
      await expect(page.locator("[data-description-fade]")).toBeHidden();

      await page.getByText("Show less").click();
      expect((await descriptionHeights(page)).shown).toBe(clamped.shown);
    });

    test("is drawn clamped from the first paint, and never moves", async ({ page }) => {
      // The HTML alone, before any script has run, already holds the clamp.
      await page.goto("/products/p-single", { waitUntil: "commit" });
      await page.waitForSelector("[data-description] p");
      const first = await descriptionHeights(page);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(300);
      expect(await descriptionHeights(page)).toEqual(first);
      expect(Math.round(first.shown / first.line)).toBe(25);
    });
  });
}

test("a short description shows in full, with no Read more", async ({ page }) => {
  await page.goto("/products/p-specs");
  await expect(page.locator("[data-description]")).toContainText("USB data link.");
  await expect(page.getByText("Read more")).toHaveCount(0);
  await expect(page.locator("[data-description-fade]")).toHaveCount(0);
  const box = await descriptionHeights(page);
  expect(box.full - box.shown).toBeLessThanOrEqual(1);
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false, viewport: PHONE });

  test("the description's Read more still opens", async ({ page }) => {
    await page.goto("/products/p-single");
    const clamped = await descriptionHeights(page);
    expect(Math.round(clamped.shown / clamped.line)).toBe(25);
    await page.getByText("Read more").click();
    await expect(page.getByText("Show less")).toBeVisible();
    const open = await descriptionHeights(page);
    expect(open.shown).toBeGreaterThan(clamped.shown);
    expect(open.shown).toBeGreaterThanOrEqual(open.full - 1);
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
  const data = await jsonLd(page, "Product");
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

    // One shop: the heading and whose listing it is, and no tab strip.
    const details = page.locator("[data-details]");
    await expect(details.getByRole("heading", { name: "What the shops say" })).toBeVisible();
    await expect(details.locator("[data-details-source]")).toHaveText([
      "From Nile Parts's listing",
    ]);
    await expect(details.locator("[data-details-tab]")).toHaveCount(0);
    await expect(details.getByRole("radiogroup")).toHaveCount(0);

    const specs = page.locator("[data-specs]");
    await expect(specs.getByRole("heading", { name: "Specifications" })).toBeVisible();
    await expect(specs.locator("dt")).toHaveText(["Model", "DC Voltage", "Display"]);
    await expect(specs.locator("dd")).toHaveText(["UT61E", "220mV – 1000V", "22000 counts"]);
    // Monospace only where the value is a part number (S3).
    await expect(specs.locator("[data-identifier]")).toHaveText(["UT61E"]);

    const sheets = page.locator("[data-datasheets]");
    await expect(sheets.getByRole("heading", { name: "Datasheets" })).toBeVisible();
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
    await expect(page.getByRole("heading", { name: "What the shops say" })).toBeVisible();
    const tabs = page.locator("[data-details-tab]");
    await expect(tabs).toHaveText(["Delta Bench", "Nile Parts"]);
    const source = page.locator("[data-details-source]:visible");
    const specs = page.locator("[data-specs]:visible");
    await expect(specs).toHaveCount(1);
    await expect(source).toHaveText("From Delta Bench's listing");
    await expect(specs.locator("dt")).toHaveText(["Flash Memory", "GPIO Pins"]);
    await expect(page.getByText("USB Chip")).toBeHidden();

    await tabs.filter({ hasText: "Nile Parts" }).click();
    await expect(source).toHaveText("From Nile Parts's listing");
    await expect(specs.locator("dt")).toHaveText(["USB Chip"]);
    await expect(page.locator("[data-datasheets]")).toHaveCount(0);
  });

  test("the selected tab is underlined in the action colour, the rest in ink-2", async ({
    page,
  }) => {
    await page.goto("/products/p-multi");
    const tabs = page.locator("[data-details-tab]");
    const ACTION = "rgb(194, 65, 12)";
    await expect(tabs.first()).toHaveCSS("border-bottom-color", ACTION);
    await expect(tabs.first()).toHaveCSS("border-bottom-width", "2px");
    await expect(tabs.last()).not.toHaveCSS("border-bottom-color", ACTION);
    const [first, last] = await tabs.evaluateAll((nodes) =>
      nodes.map((n) => getComputedStyle(n).color),
    );
    expect(first).not.toBe(last);
  });

  test("arrow keys move between shops: one radio group, one tab stop", async ({ page }) => {
    await page.goto("/products/p-multi");
    const group = page.getByRole("radiogroup", { name: "What the shops say" });
    await expect(group.getByRole("radio")).toHaveCount(2);
    await group.getByRole("radio", { name: "Delta Bench" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(group.getByRole("radio", { name: "Nile Parts" })).toBeChecked();
    await expect(page.locator("[data-specs]:visible dt")).toHaveText(["USB Chip"]);
    await page.keyboard.press("ArrowLeft");
    await expect(page.locator("[data-specs]:visible dt")).toHaveText(["Flash Memory", "GPIO Pins"]);
  });

  test("the tabs stay on one row at 320px, scrolling rather than wrapping", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    await page.goto("/products/p-multi");
    const tops = await page
      .locator("[data-details-tab]")
      .evaluateAll((nodes) => nodes.map((n) => Math.round(n.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);
    const strip = page.getByRole("radiogroup");
    expect(await strip.evaluate((n) => getComputedStyle(n).flexWrap)).toBe("nowrap");
    expect((await page.locator("[data-details-tab]").first().boundingBox())!.height).toBe(44);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
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

test.describe("readable product URLs", () => {
  const ID = "5f0c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f";
  const READABLE = `/products/${ID}-servo-motor-metal-gear-mg90s-180`;

  test("the bare id redirects permanently to the readable URL", async ({ page }) => {
    const response = await page.request.get(`/products/${ID}`, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(response.headers()["location"]).toMatch(new RegExp(`${READABLE}$`));
  });

  test("an uppercase id redirects to the one lowercase URL", async ({ page }) => {
    const response = await page.request.get(`/products/${ID.toUpperCase()}`, {
      maxRedirects: 0,
    });
    expect(response.status()).toBe(308);
    expect(response.headers()["location"]).toMatch(new RegExp(`${READABLE}$`));
  });

  test("a wrong or stale slug redirects too", async ({ page }) => {
    const response = await page.request.get(`/products/${ID}-old-title`, { maxRedirects: 0 });
    expect(response.status()).toBe(308);
    expect(response.headers()["location"]).toMatch(new RegExp(`${READABLE}$`));
  });

  test("the readable URL is the page, and its canonical", async ({ page }) => {
    const response = await page.goto(READABLE);
    expect(response?.status()).toBe(200);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      `https://makhzan.test${READABLE}`,
    );
  });

  test("breadcrumbs are marked up, ending on the product", async ({ page }) => {
    await page.goto(READABLE);
    const crumbs = await jsonLd(page, "BreadcrumbList");
    const names = crumbs.itemListElement.map((item: { name: string }) => item.name);
    expect(names.at(-1)).toBe("Servo Motor Metal Gear MG90S (180°)");
    expect(crumbs.itemListElement[0].item).toMatch(/^https:\/\/makhzan\.test\/trades\//);
  });
});

test("the page opens a connection to the main photo's server early", async ({ page }) => {
  await page.goto("/products/p-single");
  await expect(page.locator('link[rel="preconnect"][href="https://volt-corner.test"]')).toHaveCount(
    1,
  );
  // In the server's HTML: the test photos' host does not resolve, so in the
  // browser the frame swaps a failed photo for its fallback.
  const html = await (await page.request.get("/products/p-single")).text();
  expect(html).toMatch(
    /<img[^>]*caliper-1\.jpg[^>]*fetchPriority="high"|<img[^>]*fetchPriority="high"[^>]*caliper-1\.jpg/i,
  );
});
