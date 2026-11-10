import { expect, test } from "@playwright/test";

/**
 * The shop pages and the supplier page. Fixtures: tests/e2e/fixtures/shops.mjs
 * — "Shop A" checked days ago, "Stale Shop" months ago, "Gone Shop" with no
 * active listings.
 */

test("the shop list hides empty shops and marks stale ones", async ({ page }) => {
  await page.goto("/shops");
  await expect(page.getByRole("heading", { level: 1, name: "Shops" })).toBeVisible();
  await expect(page.getByText("Each is rechecked about weekly.")).toBeVisible();

  await expect(page.locator("[data-shop]")).toHaveCount(2);
  await expect(page.getByText("Gone Shop")).toHaveCount(0);

  const fresh = page.locator('[data-shop="shop-a"]');
  await expect(fresh).not.toHaveAttribute("data-stale");
  await expect(fresh).toContainText("120 products");
  await expect(fresh).toContainText("84 in stock");
  await expect(fresh).toContainText("Electronics, Tools and Chemicals");
  await expect(fresh.locator('[data-freshness="quiet"]')).toHaveText("checked 3 days ago");
  await expect(fresh.getByRole("link")).toHaveAttribute("href", "/shops/shop-a");

  const stale = page.locator('[data-shop="stale-shop"]');
  await expect(stale).toHaveAttribute("data-stale", "true");
  await expect(stale.locator('[data-freshness="warn"]')).toContainText("out of date");
});

test("a fresh shop page: stats, the way out, search and what it carries", async ({ page }) => {
  await page.goto("/shops/shop-a");
  await expect(page).toHaveTitle(/^Shop A · makhzan/);
  await expect(page.getByRole("heading", { level: 1, name: "Shop A" })).toBeVisible();
  // Under the name, and again with the address in the contact section.
  await expect(page.getByText("Bab El Louk, Cairo").first()).toBeVisible();
  await expect(page.locator("[data-stale-note]")).toHaveCount(0);
  await expect(page.locator('[data-tier="warn"]')).toHaveCount(0);
  await expect(page.locator("dl")).toContainText("Last checked3 days ago");

  // The only link out, tagged (P4).
  const visit = page.getByRole("link", { name: "Visit shop-a.test" });
  await expect(visit).toHaveAttribute("href", "https://www.shop-a.test/?ref=makhzan");
  await expect(visit).toHaveAttribute("data-umami-event-shop", "shop-a");

  // What it carries narrows the products below, on the shop's own page.
  await expect(page.getByText("Electronics 100 · Tools 15 · Chemicals 5")).toBeVisible();
  await expect(page.getByRole("link", { name: "Electronics 100" })).toHaveAttribute(
    "href",
    "/shops/shop-a?domain=electronics",
  );

  // The products are search's results, scoped to the shop: chips, toolbar,
  // and every result opens its product page (P1).
  const products = page.locator("[data-shop-products]");
  await expect(products.getByRole("link", { name: "In stock" })).toBeVisible();
  await expect(products.locator("[data-count]")).toHaveText("2 in stock");
  const results = products.locator("[data-result]");
  await expect(results).toHaveCount(2);
  await expect(results.first().getByRole("link")).toHaveAttribute("href", "/products/prod-1");

  await expect(
    page.getByRole("link", { name: "Own this shop? Add your details." }),
  ).toHaveAttribute("href", "/for-suppliers");
});

test.describe("how to reach a shop", () => {
  test("every detail: numbers, WhatsApp, email, addresses, map links, hours, and their source", async ({
    page,
  }) => {
    await page.goto("/shops/shop-a");
    const contact = page.locator("[data-shop-contact]");
    await expect(contact.getByRole("heading", { name: "Contact" })).toBeVisible();

    // Formatted for an Egyptian reader, dialled in E.164.
    const first = contact.getByRole("link", { name: "Call Shop A on 02 2345 6789" });
    await expect(first).toHaveText("02 2345 6789");
    await expect(first).toHaveAttribute("href", "tel:+20223456789");
    await expect(contact.getByRole("link", { name: "Call Shop A on 02 2345 6780" })).toBeVisible();
    await expect(
      contact.getByRole("link", { name: "WhatsApp Shop A on 010 0123 4567" }),
    ).toHaveAttribute("href", "https://wa.me/201001234567");
    await expect(contact.getByRole("link", { name: "sales@shop-a.test" })).toHaveAttribute(
      "href",
      "mailto:sales@shop-a.test",
    );

    // The main shop and its branch, each with its own map link and number.
    await expect(contact).toContainText("Main shop");
    await expect(contact).toContainText("12 Example Street, 2nd floor");
    await expect(
      contact.getByRole("link", { name: "Map: Shop A, Bab El Louk, Cairo" }),
    ).toHaveAttribute("href", "https://maps.app.goo.gl/shopA");
    await expect(contact).toContainText("Giza branch");
    await expect(
      contact.getByRole("link", { name: "Call Shop A Giza branch on 02 3333 4444" }),
    ).toHaveAttribute("href", "tel:+20233334444");
    await expect(contact).toContainText("Friday closed");

    // Quietly, where it all came from.
    await expect(contact.locator("[data-contact-source]")).toHaveText(
      "Phone, email and branches from Shop A's website, checked 3 Nov 2026, and WhatsApp and opening hours read automatically 8 Nov 2026; address and map link from Google Maps, checked 3 Nov 2026.",
    );

    // A Google Maps listing is never called the shop's own.
    await expect(contact.locator("[data-contact-source]")).not.toContainText(
      "address and map link from Shop A",
    );

    // Something wrong? An email to makhzan naming the shop and the page.
    const report = contact.getByRole("link", { name: "Tell us" });
    const href = decodeURIComponent((await report.getAttribute("href")) ?? "");
    expect(href).toMatch(/^mailto:crawler@makhzan\.merope\.dev\?subject=Something wrong: Shop A&/);
    expect(href).toContain("Page: https://makhzan.test/shops/shop-a");

    // Nothing is missing, so the foot of the page offers corrections only.
    const foot = page.locator("[data-contact-missing]");
    await expect(foot).toHaveText("Own this shop? Add your details.");
  });

  test("some details: shows them and names only what is missing", async ({ page }) => {
    await page.goto("/shops/stale-shop");
    const contact = page.locator("[data-shop-contact]");
    await expect(contact).toContainText("31 شارع المثال");
    // Nothing to call or open: only the way to report something wrong.
    await expect(contact.locator("a:not([data-contact=report])")).toHaveCount(0);
    await expect(contact.locator("[data-contact-source]")).toHaveText(
      "From Stale Shop's website, read automatically 20 Aug 2026.",
    );
    await expect(page.locator("[data-contact-missing]")).toHaveText(
      "Phone and opening hours aren't listed yet. Own this shop? Add your details.",
    );
  });

  test("no details: no empty section, and the line names all three", async ({ page }) => {
    await page.goto("/shops/gone-shop");
    await expect(page.locator("[data-shop-contact]")).toHaveCount(0);
    await expect(page.locator("[data-contact-missing]")).toHaveText(
      "Address, phone and opening hours aren't listed yet. Own this shop? Add your details.",
    );
    await expect(
      page.getByRole("link", { name: "Own this shop? Add your details." }),
    ).toHaveAttribute("href", "/for-suppliers");
  });

  test("every contact link has the shape of its kind (P4's exception)", async ({ page }) => {
    await page.goto("/shops/shop-a");
    const links = await page
      .locator("[data-shop-contact] a")
      .evaluateAll((all) =>
        all.map((a) => [a.getAttribute("data-contact"), a.getAttribute("href")]),
      );
    const shape: Record<string, RegExp> = {
      phone: /^tel:(\+\d{8,15}|1[5679]\d{3})$/,
      whatsapp: /^https:\/\/wa\.me\/\d+$/,
      email: /^mailto:[^?]+@[^?]+$/,
      map: /^https:\/\/(maps\.app\.goo\.gl|goo\.gl\/maps|g\.page|(www\.)?google\.[a-z.]+\/maps|maps\.apple\.com)\//,
      report: /^mailto:crawler@makhzan\.merope\.dev\?subject=/,
    };
    expect(new Set(links.map(([kind]) => kind))).toEqual(new Set(Object.keys(shape)));
    for (const [kind, href] of links) {
      expect(href, kind ?? "").toMatch(shape[kind ?? ""] ?? /^$-never/);
      expect(href, kind ?? "").not.toContain("ref=makhzan");
    }
  });

  test("the contact links take the link colour in the dark theme too", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/shops/shop-a");
    await expect(page.locator("html")).toHaveClass(/dark/);
    const link = page.locator('[data-shop-contact] a[data-contact="phone"]').first();
    // `link` in the dark theme: #FB923C (docs/DESIGN.md).
    await expect(link).toHaveCSS("color", "rgb(251, 146, 60)");
  });
});

test("phones list the shop's biggest categories, each narrowing its products", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/shops/shop-a");
  await expect(page.getByRole("link", { name: "Measuring Tools" })).toHaveAttribute(
    "href",
    "/shops/shop-a?category=tools%3Ameasurement",
  );
  // The rows leave out the shop's name here too.
  await expect(page.locator("[data-result]")).toHaveCount(2);
  await expect(page.locator("[data-result]").filter({ hasText: "Shop A" })).toHaveCount(0);
});

test("a shop's page uses a desktop's width, and its rows do not repeat its name", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/shops/shop-a");

  const main = page.getByRole("main");
  const products = await main.locator("[data-shop-products]").boundingBox();
  expect(products?.width ?? 0).toBeGreaterThan(1000);
  // The band uses the same width: the name at its left, the figures and the
  // way out at its right, rather than everything hugging the left.
  const name = await main.getByRole("heading", { level: 1 }).boundingBox();
  const figures = await main.locator("dl").boundingBox();
  const visit = await main.getByRole("link", { name: "Visit shop-a.test" }).boundingBox();
  expect((figures?.x ?? 0) - (name?.x ?? 0)).toBeGreaterThan(600);
  expect((visit?.x ?? 0) + (visit?.width ?? 0) - (name?.x ?? 0)).toBeGreaterThan(1000);

  // Desktop has the category rail beside the results, not the phone's list.
  await expect(page.getByRole("heading", { name: "Biggest categories here" })).toBeHidden();

  const rows = main.locator('[data-result="row"]');
  await expect(rows).toHaveCount(2);
  for (const row of await rows.all()) {
    await expect(row).not.toContainText("Shop A");
    await expect(row.locator("[data-freshness]")).toBeVisible();
  }
  // A product other shops sell too still says so.
  await expect(rows.first()).toContainText("3 shops");
});

test("the shop list fills a desktop with cards", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/shops");
  const cards = page.locator("[data-shop]");
  const first = await cards.nth(0).boundingBox();
  const second = await cards.nth(1).boundingBox();
  // Side by side, not stacked.
  expect(second?.y).toBe(first?.y);
  expect((second?.x ?? 0) - (first?.x ?? 0)).toBeGreaterThan(250);
});

test("searching a shop submits to /search scoped to it, without JavaScript", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/shops/shop-a");
  const field = page.getByRole("searchbox", { name: "Search Shop A" });
  await field.fill("lm358");
  await field.press("Enter");
  await expect(page).toHaveURL(/\/search\?shop=shop-a&q=lm358$/);
  await context.close();
});

test("the header search keeps a shop's scope, and can drop it", async ({ page }) => {
  await page.goto("/search?q=relay&shop=shop-a");
  const header = page.getByRole("banner");
  const field = header.getByRole("searchbox");
  await expect(header.getByRole("checkbox", { name: "This shop only" })).toBeChecked();
  await field.fill("lm358");
  await field.press("Enter");
  await expect(page).toHaveURL(/\/search\?shop=shop-a&q=lm358$|\/search\?q=lm358&shop=shop-a$/);

  // On the shop's own page too; unticked, it searches every shop.
  await page.goto("/shops/shop-a");
  await header.getByRole("checkbox", { name: "This shop only" }).uncheck();
  await header.getByRole("searchbox").fill("relay");
  await header.getByRole("searchbox").press("Enter");
  await expect(page).toHaveURL(/\/search\?q=relay$/);
  await expect(header.getByRole("checkbox")).toHaveCount(0);
});

test("a stale shop says so in plain language (F3)", async ({ page }) => {
  await page.goto("/shops/stale-shop");
  await expect(page.locator('[data-tier="warn"]')).toContainText("80 days ago");
  await expect(page.locator("[data-stale-note]")).toHaveText(
    /^We can't reach this shop's site at the moment\. Its prices and stock are as of \d{1,2} [A-Z][a-z]{2}( \d{4})? and may have changed\.$/,
  );
});

test("an unknown shop is a 404", async ({ page }) => {
  const response = await page.goto("/shops/no-such-shop");
  expect(response?.status()).toBe(404);
});

test("for suppliers offers four requests, each an email to the crawler's address", async ({
  page,
}) => {
  await page.goto("/for-suppliers");
  const requests = page.locator("[data-request]");
  await expect(requests).toHaveCount(4);
  await expect(requests.first()).toHaveAttribute("data-request", "remove");
  await expect(requests.first()).toContainText("within 7 days");

  for (const [id, subject] of [
    ["remove", "Remove my shop from makhzan"],
    ["add", "Add my shop to makhzan"],
    ["correct", "Correct my shop's details on makhzan"],
  ]) {
    const href = await page
      .locator(`[data-request="${id}"] a[href^="mailto:"]`)
      .getAttribute("href");
    expect(href).not.toBeNull();
    const url = new URL(href!);
    expect(url.pathname).toBe("crawler@makhzan.merope.dev");
    expect(url.searchParams.get("subject")).toBe(subject);
    expect(url.searchParams.get("body")).toContain("Shop name:");
  }

  await expect(page.getByRole("link", { name: "How we crawl, in full" })).toHaveAttribute(
    "href",
    "/how-we-crawl",
  );
});

test("the shop and supplier pages do not scroll sideways at 320px (S4)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  for (const path of [
    "/shops",
    "/shops/shop-a",
    "/shops/stale-shop",
    "/shops/gone-shop",
    "/for-suppliers",
    "/how-we-crawl",
    "/no-such-page",
  ]) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
});

test("the 404 page helps onward", async ({ page }) => {
  const response = await page.goto("/no-such-page");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("searchbox")).toBeVisible();
  const browse = page.getByRole("navigation", { name: "Browse" });
  await expect(browse.getByRole("link", { name: "All departments" })).toHaveAttribute(
    "href",
    "/departments",
  );
  await expect(browse.getByRole("link", { name: "All shops" })).toHaveAttribute("href", "/shops");
});
