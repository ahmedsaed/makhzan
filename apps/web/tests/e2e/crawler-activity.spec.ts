import { expect, test } from "@playwright/test";

/**
 * The crawler's public record: "Crawler activity" on /how-we-crawl and the line
 * on each shop's page. Fixtures: tests/e2e/fixtures/crawler.mjs — "Shop A"
 * read hours ago, "Stale Shop" paused, "New Shop" never read.
 *
 * Shop owners read this. Beyond rendering, what matters is what it never says:
 * no reason for a pause, no errors, no status codes.
 */

const FORBIDDEN = /403|blocked|error|forbidden/i;

test.describe("on a desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the section renders with totals and a row per shop", async ({ page }) => {
    await page.goto("/how-we-crawl#activity");
    const section = page.locator("#activity");
    await expect(
      section.getByRole("heading", { level: 2, name: "Crawler activity" }),
    ).toBeVisible();

    const totals = section.locator("[data-activity-totals]");
    await expect(totals).toContainText("Shops read this week1 of 3");
    await expect(totals).toContainText("Requests this week412");
    await expect(totals).toContainText("Early morning, Egypt time (03:00 UTC)");
    await expect(totals).toContainText("robots.txtHonoured");

    const table = section.getByRole("table");
    await expect(table).toBeVisible();
    const shopA = table.locator('[data-activity-shop="shop-a"]');
    await expect(shopA.getByRole("rowheader")).toHaveText("Shop Amakhzanbot · signed");
    await expect(shopA.locator("[data-identity]")).toHaveText("makhzanbot · signed");
    await expect(shopA.locator("time")).toHaveText("3 hours ago");
    // The absolute time is the tooltip.
    await expect(shopA.locator("time")).toHaveAttribute(
      "title",
      /^\d{1,2} \w{3} \d{4}, \d{2}:\d{2} UTC$/,
    );
    await expect(shopA.locator("[data-last-pass]")).toHaveText("last full pass: 6 days");
    await expect(shopA.locator("td")).toHaveText([
      "3 hours agolast full pass: 6 days",
      "412",
      "15 s",
      "16 s",
      "Active",
    ]);

    // Never read: nothing measured, and it says so plainly.
    const fresh = table.locator('[data-activity-shop="new-shop"]');
    await expect(fresh.locator("td")).toHaveText(["Not yet", "0", "—", "—", "Active"]);
    await expect(fresh.locator("[data-identity], [data-last-pass], [data-sparkline]")).toHaveCount(
      0,
    );
  });

  test("requests per day: a line per shop, an unrecorded day left out", async ({ page }) => {
    await page.goto("/how-we-crawl");
    const table = page.locator("#activity table");
    const spark = table.locator('[data-activity-shop="shop-a"] [data-sparkline]');
    await expect(spark).toHaveAttribute("role", "img");
    const label = await spark.getAttribute("aria-label");
    expect(label).toMatch(/^Requests per day, last 7 days\. /);
    expect(label).toContain("not recorded");
    expect(label?.match(/: \d+/g)).toHaveLength(6);
    // Two runs of recorded days either side of the unrecorded one: two lines,
    // not one drawn through a zero.
    await expect(spark.locator("polyline")).toHaveCount(2);
    // Nothing to draw for a shop that sent nothing this week.
    await expect(table.locator('[data-activity-shop="stale-shop"] [data-sparkline]')).toHaveCount(
      0,
    );
  });

  test("every shop's gaps together, as a histogram", async ({ page }) => {
    await page.goto("/how-we-crawl");
    const histogram = page.locator("#activity [data-gap-histogram]");
    await expect(
      histogram.getByRole("heading", { name: "How far apart our requests were this week" }),
    ).toBeVisible();
    await expect(histogram.locator("dt")).toHaveText([
      "under 15 s",
      "15 s",
      "16 s",
      "17 s",
      "18–19 s",
      "20–29 s",
      "30–59 s",
      "60 s or more",
    ]);
    await expect(histogram.locator("dd.tabular")).toHaveText([
      "0%",
      "61%",
      "19%",
      "7%",
      "5%",
      "6%",
      "<1%",
      "<1%",
    ]);
  });

  test("a paused shop shows Paused, and no reason", async ({ page }) => {
    await page.goto("/how-we-crawl");
    const row = page.locator('#activity table [data-activity-shop="stale-shop"]');
    await expect(row.locator("[data-status]")).toHaveText("Paused");
    await expect(row.locator("td")).toHaveText([/ago$/, "0", "—", "—", "Paused"]);
    await expect(row.locator("[data-identity]")).toHaveText("browser User-Agent");
  });

  test("nothing in the section speaks of errors, blocks or status codes", async ({ page }) => {
    await page.goto("/how-we-crawl");
    const section = page.locator("#activity");
    await expect(section).toBeVisible();
    expect(await section.innerText()).not.toMatch(FORBIDDEN);
    // The markup and tooltips too, not only what is visible.
    expect(await section.innerHTML()).not.toMatch(FORBIDDEN);
  });

  test("the shop page line states the facts and links to the activity", async ({ page }) => {
    await page.goto("/shops/shop-a");
    const line = page.locator("[data-crawl-activity]");
    await expect(line).toHaveText(
      "makhzan read this site 3 hours ago · 412 requests in the last 7 days · at least 15 s apart · How we crawl",
    );
    await expect(line.getByRole("link", { name: "How we crawl" })).toHaveAttribute(
      "href",
      "/how-we-crawl#activity",
    );

    await line.getByRole("link", { name: "How we crawl" }).click();
    await expect(page).toHaveURL("/how-we-crawl#activity");
    await expect(page.locator("#activity")).toBeInViewport();
  });

  test("a paused shop's page says only that we are not reading it", async ({ page }) => {
    await page.goto("/shops/stale-shop");
    const line = page.locator("[data-crawl-activity]");
    await expect(line).toHaveAttribute("data-crawl-activity", "paused");
    await expect(line).toHaveText("makhzan is not reading this site at the moment. How we crawl");
    expect(await line.innerText()).not.toMatch(FORBIDDEN);
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 375, height: 800 } });

  test("shops are stacked cards, not a table", async ({ page }) => {
    await page.goto("/how-we-crawl");
    const section = page.locator("#activity");
    await expect(section.getByRole("table")).toBeHidden();
    const card = section.locator('li[data-activity-shop="stale-shop"]');
    await expect(card).toBeVisible();
    await expect(card.locator("[data-status]")).toHaveText("Paused");
    await expect(card).toContainText("Shortest gap—");
    await expect(card).toContainText("Last full pass—");
    const shopA = section.locator('li[data-activity-shop="shop-a"]');
    await expect(shopA.locator("[data-identity]")).toHaveText("makhzanbot · signed");
    await expect(shopA).toContainText("Last full pass6 days");
    await expect(shopA.locator("[data-sparkline]")).toBeVisible();
  });

  test("the section does not scroll sideways at 320px (S4)", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    await page.goto("/how-we-crawl#activity");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
