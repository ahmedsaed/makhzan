import { expect, test, type Page } from "@playwright/test";

/**
 * /about, /faq, /contact and /terms, and the grouped footer that reaches
 * them: server-rendered, whole without JavaScript, usable by keyboard, in
 * both themes, and never wider than a phone.
 */

const PAGES = [
  { path: "/about", h1: "About makhzan", footer: "About" },
  { path: "/faq", h1: "Questions", footer: "FAQ" },
  { path: "/contact", h1: "Contact", footer: "Contact" },
  { path: "/terms", h1: "Terms of use", footer: "Terms" },
] as const;

async function noSidewaysScroll(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
}

for (const { path, h1, footer } of PAGES) {
  test(`${path} is in every footer, indexable, and fits a phone`, async ({ page }) => {
    await page.goto("/shops");
    await page.getByRole("contentinfo").getByRole("link", { name: footer, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$`));
    await expect(page.getByRole("heading", { level: 1, name: h1 })).toBeVisible();
    await expect(page.locator('meta[name="robots"][content*="noindex"]')).toHaveCount(0);
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      `https://makhzan.test${path}`,
    );

    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 800 });
      await noSidewaysScroll(page);
    }
  });
}

test("about shows the live counts from the API's totals", async ({ page }) => {
  await page.goto("/about");
  // The stub's /stats: 57,207 products from 8 shops.
  await expect(page.locator("[data-catalogue-size]")).toHaveText(
    /^Today: 57,207 products from 8 shops in \d+ departments?\.$/,
  );
  await expect(page.getByText("never by payment")).toBeVisible();
  await expect(page.getByRole("link", { name: "hello@merope.dev" })).toHaveAttribute(
    "href",
    "mailto:hello@merope.dev",
  );
});

test.describe("the FAQ", () => {
  test("opens a question by keyboard", async ({ page }) => {
    await page.goto("/faq");
    const question = page.locator("details#price-differs");
    const summary = question.locator("summary");
    await expect(question).not.toHaveAttribute("open");
    await summary.focus();
    await expect(summary).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(question).toHaveAttribute("open");
    await expect(question.getByText(/the shop’s site is right/)).toBeVisible();
    await page.keyboard.press("Space");
    await expect(question).not.toHaveAttribute("open");
    // Tab moves on to the next question.
    await summary.focus();
    await page.keyboard.press("Tab");
    await expect(page.locator("details#how-often summary")).toBeFocused();
  });

  test("opens the question a link points at", async ({ page }) => {
    await page.goto("/faq#use-data");
    await expect(page.locator("details#use-data")).toHaveAttribute("open");
    await expect(page.getByText(/no API or data licence/)).toBeVisible();
  });

  test("carries FAQPage structured data", async ({ page }) => {
    await page.goto("/faq");
    const data = JSON.parse(
      (await page.locator('script[type="application/ld+json"]').first().textContent()) ?? "{}",
    );
    expect(data["@type"]).toBe("FAQPage");
    expect(data.url).toBe("https://makhzan.test/faq");
    expect(data.mainEntity.length).toBeGreaterThan(5);
  });

  test("keeps its summaries 44 px tall on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/faq");
    for (const summary of await page.locator("summary").all()) {
      expect((await summary.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
  });
});

test.describe("without JavaScript", () => {
  test.use({ javaScriptEnabled: false });

  test("a FAQ question still opens", async ({ page }) => {
    await page.goto("/faq");
    const question = page.locator("details#is-it-a-shop");
    await question.locator("summary").click();
    await expect(question).toHaveAttribute("open");
    await expect(question.getByText(/it has no cart/)).toBeVisible();
  });

  test("about still states the counts", async ({ page }) => {
    await page.goto("/about");
    await expect(page.locator("[data-catalogue-size]")).toContainText("57,207 products");
  });
});

test("contact routes to the right addresses, with no form", async ({ page }) => {
  await page.goto("/contact");
  await expect(
    page.getByRole("link", { name: "Email crawler@makhzan.merope.dev" }),
  ).toHaveAttribute("href", "mailto:crawler@makhzan.merope.dev");
  await expect(page.getByRole("link", { name: "Email hello@merope.dev" })).toHaveAttribute(
    "href",
    "mailto:hello@merope.dev",
  );
  await expect(page.getByRole("main").getByRole("link", { name: "For suppliers" })).toHaveAttribute(
    "href",
    "/for-suppliers",
  );
  await expect(page.locator("main form")).toHaveCount(0);
  await expect(page.locator("main [data-flag-illustration]")).toContainText("Report a problem");
  await expect(page.getByRole("main").getByRole("button")).toHaveCount(0);
});

test("terms say when they were last updated", async ({ page }) => {
  await page.goto("/terms");
  await expect(page.getByText("Last updated 13 November 2026")).toBeVisible();
});

test("privacy and how-we-crawl link to contact", async ({ page }) => {
  for (const path of ["/privacy", "/how-we-crawl"]) {
    await page.goto(path);
    await expect(page.getByRole("main").locator('a[href="/contact"]')).toHaveCount(1);
  }
});

test.describe("in dark mode", () => {
  test.use({ colorScheme: "dark" });

  for (const { path } of PAGES) {
    test(`${path} uses the dark tokens`, async ({ page }) => {
      await page.goto(path);
      await expect(page.locator("html")).toHaveClass(/dark/);
      // `ground` and `surface`, dark (docs/DESIGN.md).
      expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(
        "rgb(18, 19, 22)",
      );
      expect(
        await page.locator("footer").evaluate((el) => getComputedStyle(el).backgroundColor),
      ).toBe("rgb(27, 29, 33)");
    });
  }
});

test.describe("the footer on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("puts its groups in two columns, every link 44 px, nothing sideways", async ({ page }) => {
    await page.goto("/about");
    const footer = page.getByRole("contentinfo");
    await footer.scrollIntoViewIfNeeded();
    const boxes = await Promise.all(
      ["makhzan", "For shops", "Legal"].map(
        async (name) => (await footer.locator(`[data-footer-group="${name}"]`).boundingBox())!,
      ),
    );
    // makhzan and For shops side by side; Legal under makhzan.
    expect(Math.abs(boxes[0].y - boxes[1].y)).toBeLessThan(2);
    expect(boxes[1].x).toBeGreaterThan(boxes[0].x);
    expect(boxes[2].y).toBeGreaterThan(boxes[0].y);
    for (const link of await footer.getByRole("navigation").getByRole("link").all()) {
      expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    for (const button of await footer
      .getByRole("group", { name: "Theme" })
      .getByRole("button")
      .all()) {
      expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    await noSidewaysScroll(page);
  });
});
