import { expect, test, type Page } from "@playwright/test";

/**
 * The shop terms on the product page (docs/PRODUCT.md, Phase 2), one test
 * group per case of the owner-approved mockup. Products are the stub's
 * (tests/e2e/fixtures/phase2.mjs); the rules themselves are unit-tested in
 * tests/offers.test.ts, so these check that the page says them, in the
 * server's HTML, at phone and desktop widths, with and without JavaScript.
 */

const PHONE = { width: 375, height: 812 };
const DESKTOP = { width: 1280, height: 900 };

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("one shop", () => {
  test.use({ viewport: DESKTOP });

  test("options: range across in-stock options, six rows, the rest folded", async ({ page }) => {
    await page.goto("/products/p2-options");
    const box = page.locator("[data-buy]");
    await expect(box.locator("[data-price]").first()).toHaveText("EGP 1,700 – 1,750");
    const options = page.locator("section[data-options]");
    await expect(options.getByRole("heading", { name: "8 options" })).toBeVisible();
    await expect(options).toContainText("at Sphinx 3D · read");
    await expect(options.locator("[data-option]:visible")).toHaveCount(6);
    await expect(options.locator("tr", { hasText: "Gray" })).toContainText("see shop");
    await options.getByText("Show 2 more options").click();
    await expect(options.locator("[data-option]:visible")).toHaveCount(8);
    await expect(options.locator("tr", { hasText: "Orange" })).toContainText("Out of stock");
    await expect(options).toContainText("6 of 8 in stock.");
  });

  test("videos are links to their host, without ref=makhzan", async ({ page }) => {
    await page.goto("/products/p2-options");
    const video = page.locator("[data-videos] a[data-video]");
    await expect(video).toHaveText(/eSUN ASA\+ print test\s*on YouTube/);
    await expect(video).toHaveAttribute("href", "https://www.youtube.com/watch?v=asa-test");
    await expect(video).toHaveAttribute("target", "_blank");
  });

  test("minimum order: each, the minimum with its total, the stated part number", async ({
    page,
  }) => {
    await page.goto("/products/p2-minorder");
    const box = page.locator("[data-buy]");
    await expect(box.locator("[data-price]").first()).toHaveText("EGP 0.15");
    await expect(box.locator("[data-each]").first()).toHaveText("each");
    await expect(box.locator("[data-minimum]")).toHaveText("min. 10 (EGP 1.50), then in tens");
    await expect(page.locator("[data-mfr-part]")).toHaveText(
      "Mfr. part number FRC0603F6803TS · from Cairo Makers's listing",
    );
    await expect(page.locator("[data-mfr-part] [data-identifier]")).toHaveCSS(
      "font-family",
      /Plex|mono/i,
    );
  });

  test("quantity prices: the shop's tiers, each", async ({ page }) => {
    await page.goto("/products/p2-breaks");
    const table = page.locator("[data-price-breaks]");
    await expect(table).toContainText("as Giza Robotics lists it");
    await expect(table.locator("tbody tr")).toHaveText([
      /1–9\s*EGP 47 each/,
      /10–49\s*EGP 44 each/,
      /50 or more\s*EGP 42 each/,
    ]);
    // The headline stays the price of one without "each": no minimum here.
    await expect(page.locator("[data-buy] [data-each]")).toHaveCount(0);
  });

  test("price on request: never EGP 0, and points to the contact buttons", async ({ page }) => {
    await page.goto("/products/p2-por");
    const box = page.locator("[data-buy]");
    await expect(box.locator("[data-on-request]").first()).toHaveText("Price on request");
    await expect(box).not.toContainText("EGP 0");
    await expect(box.locator("[data-stock]")).toHaveText("Available at Sphinx 3D");
    await expect(box.locator("[data-on-request-note]")).toHaveText(
      "Sphinx 3D gives this price on request: call or message them below.",
    );
    await expect(box.locator("[data-fits]")).toHaveText("Fits K2 Plus");
  });

  test("fits and ships from abroad: neutral pills, more than two models fold", async ({ page }) => {
    await page.goto("/products/p2-badges");
    const box = page.locator("[data-buy]");
    await expect(box.locator("[data-abroad]")).toHaveText("Ships from abroad");
    const fits = box.locator("details[data-fits]");
    await expect(fits.locator("summary")).toHaveText("Fits 19 models");
    await expect(fits.getByText("Phrozen Shuffle")).toBeHidden();
    await fits.locator("summary").click();
    await expect(fits.getByText("Phrozen Shuffle")).toBeVisible();
  });

  test("a stock count shows only where the shop publishes one", async ({ page }) => {
    await page.goto("/products/p2-options");
    await expect(page.locator("[data-buy] [data-stock]")).toHaveText("In stock at Sphinx 3D");
  });
});

test.describe("several shops", () => {
  test.use({ viewport: DESKTOP });

  test("mixed minimums: compared by the price of one, each and the minimum beside it", async ({
    page,
  }) => {
    await page.goto("/products/p2-mixedmin");
    const summary = page.locator("[data-summary]");
    await expect(summary.locator("[data-price]").first()).toHaveText("EGP 0.15 – 2");
    await expect(summary.locator("[data-each]")).toHaveText("each");
    await expect(summary.locator("[data-lowest-minimum]")).toHaveText(
      "Lowest needs a minimum order: 10 (EGP 1.50) at Cairo Makers",
    );
    await expect(summary.locator("[data-primary]")).toHaveText("EGP 0.15 each at Cairo Makers");
    await expect(summary.locator("[data-primary-notes]")).toHaveText("min. 10 (EGP 1.50)");
    await expect(page.locator("[data-fact=shops]")).toContainText("EGP 0.15 – 2 each");
    const first = page.locator("[data-offer]").first();
    await expect(first).toContainText("EGP 0.15each");
    await expect(first.locator('[data-term="minimum"]')).toHaveText("min. 10 (EGP 1.50)");
  });

  test("some on request: out of the range, sorted after the priced", async ({ page }) => {
    await page.goto("/products/p2-somepor");
    const summary = page.locator("[data-summary]");
    await expect(summary.locator("[data-summary-text]")).toHaveText(
      "2 offers in stock at 2 shops · 1 more on request",
    );
    await expect(summary.locator("[data-price]").first()).toHaveText("EGP 1,450 – 1,500");
    await expect(summary.locator("[data-primary]")).toHaveText("EGP 1,450 at Giza Robotics");
    const rows = page.locator("[data-offer]:visible");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(2)).toContainText("Price on request");
    await expect(rows.nth(2)).toContainText("Sphinx 3D");
  });

  test("all on request: the headline says so and the button opens the newest", async ({ page }) => {
    await page.goto("/products/p2-allpor");
    const summary = page.locator("[data-summary]");
    await expect(summary.locator("[data-summary-text]")).toHaveText(
      "2 offers in stock at 2 shops, prices on request",
    );
    await expect(summary.locator("[data-on-request]")).toHaveText("Price on request");
    await expect(summary.locator("[data-primary]")).toHaveText("View at Giza Robotics");
    await expect(page.locator("[data-fact=shops]")).toContainText("· prices on request");
    await expect(page.locator("main")).not.toContainText("EGP 0");
  });

  test("a cheaper in-stock option counts and is named", async ({ page }) => {
    await page.goto("/products/p2-cheapopt");
    const summary = page.locator("[data-summary]");
    await expect(summary.locator("[data-price]").first()).toHaveText("EGP 320 – 355");
    await expect(summary.locator("[data-lowest-option]")).toHaveText(
      "Lowest is the “Without headers” option at Cairo Makers.",
    );
    await expect(summary.locator("[data-primary]")).toHaveText("EGP 320 at Cairo Makers");
    await expect(summary.locator("[data-primary-notes]")).toHaveText("“Without headers” option");
    const row = page.locator("[data-offer]").first();
    await expect(row.locator("[data-price]")).toHaveText("EGP 320 – 380");
    await row.getByText("3 options · 2 in stock").click();
    await expect(row.locator("[data-option]")).toHaveCount(3);
  });

  test("quantity hint, stock count on its row, the stale lowest folded", async ({ page }) => {
    await page.goto("/products/p2-volume");
    const summary = page.locator("[data-summary]");
    await expect(summary.locator("[data-price]").first()).toHaveText("EGP 55 – 90");
    await expect(summary.locator("[data-quantity-hint]")).toHaveText(
      "Buying 100 or more? Giza Robotics lists EGP 35 each from 100.",
    );
    await expect(summary.locator("[data-primary]")).toHaveText("EGP 55 at Giza Robotics");
    await expect(page.locator('[data-term="count"]')).toHaveText("74 in stock");
    await expect(page.locator("[data-stale] summary")).toHaveText(/Show 1 out of date offer/);
    await expect(page.locator("[data-out-of-stock] summary")).toHaveText(
      /Show 1 out of stock offer/,
    );
  });

  test("part numbers that disagree: one line, each row its own", async ({ page }) => {
    await page.goto("/products/p2-mfrs");
    await expect(page.locator("[data-also-stated]")).toHaveText(
      "· also stated by Delta Components",
    );
    await expect(page.locator("[data-mfr-disagree]")).toHaveText(
      "Shops state 2 manufacturer part numbers: NE555P, NE555 · each offer shows its own",
    );
    await expect(page.locator('[data-term="mfr"]')).toHaveText([
      "Mfr. part NE555P",
      "Mfr. part NE555",
    ]);
  });

  test("Fits stays on each row; ships from abroad follows the button", async ({ page }) => {
    await page.goto("/products/p2-fits");
    const summary = page.locator("[data-summary]");
    await expect(summary.locator("[data-primary]")).toHaveText("EGP 15 at Bazaar Hub");
    await expect(summary.locator("[data-primary-notes]")).toHaveText("ships from abroad");
    const fits = page.locator("[data-offer] [data-fits]");
    await expect(fits.first()).toHaveText("Fits Ender 3, Anet A8");
    await expect(fits.nth(1).locator("summary")).toHaveText("Fits 4 models");
    // Never merged: the first row's list is not repeated on the second.
    await expect(fits).toHaveCount(2);
  });

  test("TB6600: every per-row line at once", async ({ page }) => {
    await page.goto("/products/p2-multi");
    await expect(page.locator('[data-term="count"]')).toHaveText("36 in stock");
    await expect(page.locator('[data-term="breaks"]').first()).toHaveText(
      "EGP 415 from 10, EGP 405 from 50",
    );
    await expect(page.locator("[data-mfr-part]")).toContainText("TB6600HG");
  });
});

test.describe("phones", () => {
  test.use({ viewport: PHONE });

  test("the bottom bar carries each, the minimum and ships from abroad", async ({ page }) => {
    await page.goto("/products/p2-mixedmin");
    const bar = page.locator("[data-bottom-bar]");
    await expect(bar.locator("[data-price]")).toHaveText("EGP 0.15");
    await expect(bar.locator("[data-each]")).toHaveText("each");
    await expect(bar.locator("[data-bar-notes]")).toHaveText("min. 10 (EGP 1.50)");
    await page.goto("/products/p2-fits");
    await expect(page.locator("[data-bottom-bar] [data-bar-notes]")).toHaveText(
      "ships from abroad",
    );
    await page.goto("/products/p2-allpor");
    await expect(page.locator("[data-bottom-bar]")).toContainText("Price on request");
    await expect(page.locator("[data-bottom-bar]")).toContainText("View at Giza Robotics");
  });

  for (const id of [
    "p2-options",
    "p2-minorder",
    "p2-breaks",
    "p2-por",
    "p2-badges",
    "p2-multi",
    "p2-mixedmin",
    "p2-somepor",
    "p2-allpor",
    "p2-cheapopt",
    "p2-volume",
    "p2-mfrs",
    "p2-fits",
  ]) {
    test(`${id} has no sideways scroll at 375px`, async ({ page }) => {
      await page.goto(`/products/${id}`);
      // Open every fold: an open table must fit too.
      await page.evaluate(() =>
        document.querySelectorAll("details").forEach((d) => d.setAttribute("open", "")),
      );
      await noSideScroll(page);
    });
  }
});

test.describe("layout under stress", () => {
  for (const width of [320, 375]) {
    test(`long and Arabic option names keep their room at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto("/products/p2-options-long");
      const options = page.locator("section[data-options]");
      await expect(options.locator("[data-option]:visible")).toHaveCount(6);
      await options.getByText("Show 3 more options").click();
      await expect(options.locator("[data-option]:visible")).toHaveCount(9);
      // The name column is the widest: price and stock stay narrow on a phone.
      const name = await options.locator("[data-option] td").first().boundingBox();
      const stock = await options.locator("[data-option] td").nth(2).boundingBox();
      expect(name!.width).toBeGreaterThan(stock!.width);
      await expect(options.getByText("أسود مطفي")).toHaveAttribute("dir", "auto");
      await noSideScroll(page);
    });
  }

  test("options read over 45 days ago: a quiet cue, no bold stock, no price set", async ({
    page,
  }) => {
    await page.goto("/products/p2-options-long");
    const options = page.locator("section[data-options]");
    await expect(options.locator("[data-options-read]")).toHaveText(/^as read \d+ \w+/);
    await expect(options).toContainText("over 45 days old");
    const inStock = options.locator("[data-option] td", { hasText: "1,200 in stock" });
    await expect(inStock).toHaveCSS("font-weight", "400");
    // The headline is the listing price alone: stale options widen nothing.
    await expect(page.locator("[data-buy] [data-price]").first()).toHaveText("EGP 950");
  });

  test("the rows behind 'Show more' have a head for screen readers", async ({ page }) => {
    await page.goto("/products/p2-options-long");
    await expect(page.locator("[data-options-more] thead")).toHaveClass(/sr-only/);
  });

  for (const width of [320, 375]) {
    test(`the bottom bar keeps "View at" readable beside long notes at ${width}px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 700 });
      await page.goto("/products/p2-longnotes");
      const bar = page.locator("[data-bottom-bar]");
      const button = await bar.getByRole("link", { name: /View at/ }).boundingBox();
      expect(button!.width).toBeGreaterThanOrEqual(150);
      const notes = bar.locator("[data-bar-notes]");
      await expect(notes).toContainText("min. 10 (EGP 2,400)");
      await expect(notes).toContainText("ships from abroad");
      const box = await notes.boundingBox();
      // Two lines of 12px text at most.
      expect(box!.height).toBeLessThanOrEqual(36);
      await noSideScroll(page);
    });
  }

  test("one shop with a minimum: the box and the bar say the same price", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p2-minorder");
    const box = page.locator("[data-buy]");
    const bar = page.locator("[data-bottom-bar]");
    await expect(box.locator("[data-price]").first()).toHaveText("EGP 0.15");
    await expect(bar.locator("[data-price]")).toHaveText("EGP 0.15");
    await expect(bar.locator("[data-each]")).toHaveText("each");
    await expect(bar.locator("[data-bar-notes]")).toHaveText("min. 10 (EGP 1.50)");
  });

  test("all offers on request: no 'lowest price first'", async ({ page }) => {
    await page.goto("/products/p2-allpor");
    await expect(page.getByText("lowest price first")).toHaveCount(0);
    await page.goto("/products/p2-somepor");
    await expect(page.getByText("lowest price first")).toHaveCount(1);
  });
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false, viewport: PHONE });

  test("the folds open: options, Fits, a row's options", async ({ page }) => {
    await page.goto("/products/p2-options");
    await page.getByText("Show 2 more options").click();
    await expect(page.locator("section[data-options] [data-option]:visible")).toHaveCount(8);
    await page.goto("/products/p2-badges");
    await page.locator("details[data-fits] summary").click();
    await expect(page.getByText("Phrozen Shuffle")).toBeVisible();
    await page.goto("/products/p2-cheapopt");
    await page.getByText("3 options · 2 in stock").click();
    await expect(page.locator("[data-offer] [data-option]")).toHaveCount(3);
  });
});

test.describe("price history", () => {
  test.use({ viewport: DESKTOP });

  test("one shop: facts line and card, server-rendered", async ({ page }) => {
    await page.goto("/products/p2-options");
    await expect(page.locator("[data-fact=history]")).toHaveText(
      "Lowest in 90 days EGP 1,650 · in stock 10 of the last 12 weeks · Price history",
    );
    const card = page.locator("[data-history=price]");
    await expect(card.getByRole("heading", { name: "Price history" })).toBeVisible();
    await expect(card).toContainText("last 90 days");
    await expect(card.locator("[data-history-now]")).toContainText("EGP 1,700");
    await expect(card.locator("[data-history-lowest]")).toContainText("EGP 1,650");
    await expect(card.locator('[data-step="out"]')).toHaveCount(2);
    await expect(card.locator("[data-weeks]")).toContainText("In stock 10 of the last 12 weeks");
    await expect(card).toContainText("Dashed: out of stock.");
  });

  test("several shops: the lowest names its shop, gaps shaded, the table says it all", async ({
    page,
  }) => {
    await page.goto("/products/p2-histmulti");
    const card = page.locator("[data-history=price]");
    await expect(card.locator("[data-history-lowest]")).toContainText("at Delta Components");
    await expect(card.locator("[data-gap]")).toHaveCount(1);
    await expect(card).toContainText("none in stock");
    await expect(card.locator("[data-weeks]")).toContainText("(at one shop or more)");
    await card.getByText("Show as a table").click();
    const rows = card.locator("[data-history-table] tbody tr");
    await expect(rows).toHaveCount(5);
    await expect(rows.nth(2)).toContainText("None in stock");
    await expect(rows.nth(1)).toContainText("Delta Components");
  });

  test("the tooltip names the price and the shop (JavaScript only)", async ({ page }) => {
    await page.goto("/products/p2-histmulti");
    const plot = page.locator("[data-chart] svg");
    await plot.scrollIntoViewIfNeeded();
    const box = (await plot.boundingBox())!;
    // Until hydration the plot has no handler: keep moving until the tip shows.
    await expect(async () => {
      await page.mouse.move(box.x + box.width - 10, box.y + box.height / 2);
      await page.mouse.move(box.x + box.width - 4, box.y + box.height / 2);
      await expect(page.locator("[data-chart-tip]")).toBeVisible({ timeout: 500 });
    }).toPass();
    await expect(page.locator("[data-chart-tip]")).toContainText("Delta Components");
    await expect(page.locator("[data-chart-tip]")).toContainText("EGP 320");
  });

  test("before 90 days: 'Lowest since', no strip", async ({ page }) => {
    await page.goto("/products/p2-breaks");
    const card = page.locator("[data-history=price]");
    await expect(card.locator("[data-history-lowest]")).toContainText(/Lowest since \d+ \w+/);
    await expect(card.locator("[data-weeks]")).toHaveCount(0);
    await expect(page.locator("[data-fact=history]")).toHaveText(
      /^Lowest since \d+ \w+ EGP 45 · Price history$/,
    );
  });

  test("nothing priced: a stock history only", async ({ page }) => {
    await page.goto("/products/p2-allpor");
    const card = page.locator("[data-history=stock]");
    await expect(card.getByRole("heading", { name: "Stock history" })).toBeVisible();
    await expect(card.locator("[data-chart]")).toHaveCount(0);
    await expect(page.locator("[data-fact=history]")).toHaveText(
      "in stock every week of the last 12 · Stock history",
    );
  });

  test("no card, and no line, without history or under 30 days of it", async ({ page }) => {
    for (const id of ["p2-por", "p2-mfrs", "p-single"]) {
      await page.goto(`/products/${id}`);
      await expect(page.locator("[data-history]")).toHaveCount(0);
      await expect(page.locator("[data-fact=history]")).toHaveCount(0);
    }
  });

  test("works at 375px without JavaScript and without sideways scroll", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: PHONE });
    const page = await context.newPage();
    for (const id of ["p2-options", "p2-histmulti", "p2-multi", "p2-volume"]) {
      await page.goto(`/products/${id}`);
      await expect(page.locator("[data-history=price] [data-chart] svg")).toBeVisible();
      await page.locator("[data-history-table] summary").click();
      await expect(page.locator("[data-history-table] tbody tr").first()).toBeVisible();
      await noSideScroll(page);
    }
    await context.close();
  });
});
