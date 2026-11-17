import { expect, test, type Locator, type Page } from "@playwright/test";

/**
 * The shop view and "Matched by AI" on a product page (docs/DESIGN.md; the
 * approved mockup of November 2026). The product, p-ai, is in
 * tests/e2e/fixtures/shop-view.mjs: five fictional shops, Nile Parts the
 * cheapest in stock, Volt Corner and Oasis Parts Lab matched by AI, Delta
 * Bench with no photo and nothing written, Sinai Spares out of stock.
 */

const URL = "/products/p-ai";
const NILE_TITLE = "TB6600 Stepper Motor Driver 4A 9-42V 32 Microstep";
const VOLT_TITLE = "TB6600 4A Stepper Driver Module for NEMA 17 / NEMA 23";
const OASIS_TITLE = "Stepper Driver TB6600 Upgraded (TB67S109 chip) 4A";
const PRODUCT_TITLE = "TB6600 Stepper Motor Driver 4A 9–42V";
const TIP =
  "makhzan’s AI judged this the same product as the others; the rules alone didn’t. Check the shop’s page before buying.";
const DESKTOP = { width: 1280, height: 900 };
const PHONE = { width: 390, height: 844 };

const row = (page: Page, id: string) => page.locator(`[data-offer="${id}"]`);
const tab = (page: Page, name: RegExp) =>
  page.getByRole("radiogroup", { name: "What the shops say" }).getByRole("radio", { name });
const primary = (page: Page) => page.locator("[data-summary] [data-primary]");
const bar = (page: Page) => page.locator("[data-bottom-bar]");

/** Which photo the gallery strip has scrolled to, from 0. */
async function galleryIndex(page: Page): Promise<number> {
  return page.locator("[data-gallery]").evaluate((track) => {
    const [a, b] = Array.from(track.children) as HTMLElement[];
    const step = b.getBoundingClientRect().left - a.getBoundingClientRect().left;
    return Math.round(track.scrollLeft / step);
  });
}

async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

/** As touch-targets.spec.ts measures it: the run a tap resolves to the control. */
async function tapHeight(control: Locator): Promise<number> {
  return control.evaluate((element) => {
    element.scrollIntoView({ block: "center" });
    const box = element.getBoundingClientRect();
    const x = box.left + Math.min(box.width / 2, 8);
    const hits = (y: number) => {
      const found = document.elementFromPoint(x, y);
      return found !== null && (found === element || element.contains(found));
    };
    let top = box.top + box.height / 2;
    let bottom = top;
    while (top > box.top - 24 && hits(top - 1)) top -= 1;
    while (bottom < box.bottom + 24 && hits(bottom + 1)) bottom += 1;
    return bottom - top + 1;
  });
}

test.describe("on load", () => {
  test.use({ viewport: DESKTOP });

  test("the cheapest offer's shop is picked: title, ring, tab and button", async ({ page }) => {
    await page.goto(URL);
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);
    await expect(row(page, "o-ai-nile")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[aria-current]")).toHaveCount(1);
    await expect(row(page, "o-ai-nile").getByText("Showing this listing")).toBeVisible();
    await expect(tab(page, /^Nile Parts/)).toBeChecked();
    await expect(primary(page)).toHaveText("EGP 385 at Nile Parts");
    // The product's photo leads, as before the shop view.
    expect(await galleryIndex(page)).toBe(0);
    // Loading changes no URL.
    expect(page.url()).not.toContain("shop=");
  });

  test("a product with no AI-matched offer has no badge and no note", async ({ page }) => {
    await page.goto("/products/p-multi");
    await expect(page.locator("[data-ai-note]")).toHaveCount(0);
    await expect(page.locator("[data-ai-badge], [data-ai-pill]")).toHaveCount(0);
    // The shop view is there all the same.
    await expect(page.locator("[data-view-listing]").first()).toBeVisible();
  });

  test("a one-shop page has no shop view", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.locator("h1")).toHaveText("Digital Caliper 150mm x 0.01mm IP54");
    await expect(page.locator("[data-view-listing], [data-showing-listing]")).toHaveCount(0);
  });
});

test.describe("matched by AI", () => {
  test.use({ viewport: DESKTOP });

  test("a badge on each AI-matched row and its shop's tab", async ({ page }) => {
    await page.goto(URL);
    const badges = page.locator("[data-ai-badge]");
    await expect(badges).toHaveCount(2);
    await expect(row(page, "o-ai-volt").locator("[data-ai-badge]")).toHaveAccessibleName(
      "Matched by AI: check the shop’s page before buying",
    );
    await expect(row(page, "o-ai-oasis").locator("[data-ai-badge]")).toHaveCount(1);
    await expect(row(page, "o-ai-nile").locator("[data-ai-badge]")).toHaveCount(0);
    await expect(tab(page, /^Volt Corner, matched by AI$/)).toHaveCount(1);
    await expect(tab(page, /^Oasis Parts Lab, matched by AI$/)).toHaveCount(1);
    await expect(tab(page, /^Nile Parts$/)).toHaveCount(1);
    await expect(page.locator("label[data-details-tab] [data-ai-pill]")).toHaveCount(2);
    // A neutral pill (line-strong outline, surface, ink-2), never the badge colours.
    const look = await badges.first().evaluate((el) => {
      const s = getComputedStyle(el);
      return { border: s.borderTopColor, bg: s.backgroundColor, color: s.color };
    });
    // line-strong #D5D5CF, surface #FFFFFF, ink-2 #4A4F5A (light).
    expect(look).toEqual({
      border: "rgb(213, 213, 207)",
      bg: "rgb(255, 255, 255)",
      color: "rgb(74, 79, 90)",
    });
  });

  test("the tooltip opens on hover, and from the keyboard; Esc closes it", async ({ page }) => {
    await page.goto(URL);
    const badge = row(page, "o-ai-volt").locator("[data-ai-badge]");
    await badge.hover();
    const tip = page.locator("[data-ai-tip]");
    await expect(tip).toBeVisible();
    await expect(tip).toContainText("Matched by AI");
    await expect(tip).toContainText(TIP);
    await page.mouse.move(5, 5);
    await expect(tip).toBeHidden();

    await badge.focus();
    await page.keyboard.press("Enter");
    await expect(tip).toBeVisible();
    // Information only: focus stays on the badge.
    await expect(badge).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(tip).toBeHidden();
    await expect(badge).toBeFocused();
  });

  test("the note sits under the title with the facts, and “tell us” opens the report", async ({
    page,
  }) => {
    await page.goto(URL);
    const note = page.locator("[data-ai-note]");
    await expect(note).toHaveText(
      "2 of 5 offers were matched automatically by AI. If one isn’t the same product, tell us.",
    );
    // In the title's column, after the facts, before the summary.
    const facts = await page.locator("h1").evaluate((h1) => {
      const note = document.querySelector("[data-ai-note]")!;
      const summary = document.querySelector("[data-summary]")!;
      const title = h1.closest(".lg\\:row-start-1")!;
      return {
        inTitleColumn: title.contains(note),
        afterTitle: Boolean(h1.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING),
        beforeSummary: Boolean(
          note.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
        ),
      };
    });
    expect(facts).toEqual({ inTitleColumn: true, afterTitle: true, beforeSummary: true });

    await note.getByRole("button", { name: "tell us" }).click();
    const dialog = page.getByRole("dialog", { name: "Report a problem" });
    await expect(dialog.getByText("Step 2 of 2")).toBeVisible();
    await expect(dialog.getByText("These offers aren’t the same product")).toBeVisible();
    const boxes = dialog.getByRole("checkbox");
    await expect(boxes).toHaveCount(5);
    expect(await boxes.evaluateAll((all) => all.map((b) => (b as HTMLInputElement).value))).toEqual(
      ["o-ai-volt", "o-ai-oasis", "o-ai-nile", "o-ai-delta", "o-ai-sinai"],
    );
    for (const box of await boxes.all()) await expect(box).not.toBeChecked();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("dark mode: the pill and the tooltip in the dark tokens", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto(URL);
    const badge = row(page, "o-ai-volt").locator("[data-ai-badge]");
    await badge.hover();
    await expect(page.locator("[data-ai-tip]")).toBeVisible();
    const colours = await page.evaluate(() => {
      const badge = document.querySelector("[data-ai-badge]")!;
      const tip = document.querySelector("[data-ai-tip]")!;
      return {
        badgeBg: getComputedStyle(badge).backgroundColor,
        tipBg: getComputedStyle(tip).backgroundColor,
        tipInk: getComputedStyle(tip).color,
      };
    });
    // surface #1B1D21, ink #ECECEA, ground #121316.
    expect(colours).toEqual({
      badgeBg: "rgb(27, 29, 33)",
      tipBg: "rgb(236, 236, 234)",
      tipInk: "rgb(18, 19, 22)",
    });
  });
});

test.describe("picking a shop", () => {
  test.use({ viewport: DESKTOP });

  test("by its tab: title, gallery, ring, tab, button and URL follow", async ({ page }) => {
    await page.goto(URL);
    const before = await page.evaluate(() => history.length);
    await page
      .getByRole("radiogroup", { name: "What the shops say" })
      .locator("label", { hasText: "Volt Corner" })
      .click();
    await expect(page.locator("h1")).toHaveText(VOLT_TITLE);
    await expect(row(page, "o-ai-volt")).toHaveAttribute("aria-current", "true");
    await expect(row(page, "o-ai-nile")).not.toHaveAttribute("aria-current");
    // An inset 2px ring in the link colour, on the ground fill.
    const ring = await row(page, "o-ai-volt").evaluate((el) => getComputedStyle(el).boxShadow);
    expect(ring).toContain("inset");
    await expect(tab(page, /^Volt Corner/)).toBeChecked();
    await expect(page.locator("[data-details-source]:visible")).toHaveText(
      "From Volt Corner's listing",
    );
    await expect(primary(page)).toHaveText("EGP 410 at Volt Corner");
    await expect(primary(page)).toHaveAttribute("href", /volt-corner\.test\/p\/o-ai-volt/);
    await expect.poll(() => galleryIndex(page)).toBe(3);
    await expect(page).toHaveURL(/\/products\/p-ai\?shop=volt-corner$/);
    // replaceState: no history entry per pick.
    expect(await page.evaluate(() => history.length)).toBe(before);
    await expect(page.locator("[data-shop-view-status]")).toHaveText(
      "Showing Volt Corner’s listing",
    );
  });

  test("by “View listing”, and the arrow keys move between tabs", async ({ page }) => {
    await page.goto(URL);
    await row(page, "o-ai-oasis")
      .getByRole("link", { name: /View Oasis Parts Lab’s listing/ })
      .click();
    await expect(page.locator("h1")).toHaveText(OASIS_TITLE);
    await expect(row(page, "o-ai-oasis").getByText("Showing this listing")).toBeVisible();
    await expect(tab(page, /^Oasis Parts Lab/)).toBeChecked();
    await expect(primary(page)).toHaveText("EGP 450 at Oasis Parts Lab");
    await expect.poll(() => galleryIndex(page)).toBe(1);
    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);

    await tab(page, /^Oasis Parts Lab/).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);
    await expect(page).toHaveURL(/\?shop=nile-parts$/);
  });

  test("a shop with no photo and no tab keeps the photo and the open tab", async ({ page }) => {
    await page.goto(URL);
    await row(page, "o-ai-volt")
      .getByRole("link", { name: /View Volt Corner’s listing/ })
      .click();
    await expect.poll(() => galleryIndex(page)).toBe(3);
    await row(page, "o-ai-delta")
      .getByRole("link", { name: /View Delta Bench’s listing/ })
      .click();
    await expect(page.locator("h1")).toHaveText(
      "TB6600 Stepper Motor Driver Controller 4.0A 42VDC",
    );
    await expect(tab(page, /^Volt Corner/)).toBeChecked();
    expect(await galleryIndex(page)).toBe(3);
    await expect(primary(page)).toHaveText("EGP 425 at Delta Bench");
  });

  test("a folded offer's fold opens when its shop is picked by link", async ({ page }) => {
    await page.goto(`${URL}?shop=sinai-spares`);
    await expect(page.locator("details[data-out-of-stock]")).toHaveAttribute("open", "");
    await expect(row(page, "o-ai-sinai")).toBeVisible();
    await expect(row(page, "o-ai-sinai")).toHaveAttribute("aria-current", "true");
    // Out of stock: the button names the shop, not a price.
    await expect(primary(page)).toHaveText("View at Sinai Spares");
  });

  test("the ring follows the box's rounded corners on its first and last rows", async ({
    page,
  }) => {
    // The box clips its rows; a square ring on a corner row was cut off there.
    const radii = (id: string) =>
      row(page, id).evaluate((el) => {
        const s = getComputedStyle(el);
        return {
          top: parseFloat(s.borderTopLeftRadius),
          bottom: parseFloat(s.borderBottomLeftRadius),
        };
      });
    await page.goto(`${URL}?shop=nile-parts`);
    expect((await radii("o-ai-nile")).top).toBeGreaterThan(0);
    expect(await radii("o-ai-delta")).toEqual({ top: 0, bottom: 0 });
    // The last in-stock row is not the box's last: the fold follows it.
    expect((await radii("o-ai-oasis")).bottom).toBe(0);
    await page.goto(`${URL}?shop=sinai-spares`);
    await expect(row(page, "o-ai-sinai")).toHaveAttribute("aria-current", "true");
    expect((await radii("o-ai-sinai")).bottom).toBeGreaterThan(0);
  });

  test("with reduced motion the gallery jumps rather than glides", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto(URL);
    await row(page, "o-ai-volt")
      .getByRole("link", { name: /View Volt Corner’s listing/ })
      .click();
    // Read in the same task as the click lands: no animation to wait for.
    expect(await galleryIndex(page)).toBe(3);
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: PHONE, hasTouch: true });

  test("the box is square edge to edge, and so is the ring", async ({ page }) => {
    await page.goto(URL);
    const radius = await row(page, "o-ai-nile").evaluate(
      (el) => getComputedStyle(el).borderTopLeftRadius,
    );
    expect(radius).toBe("0px");
  });

  test("the bottom bar and the thumbnail follow the picked shop", async ({ page }) => {
    await page.goto(URL);
    await expect(bar(page).getByRole("link")).toHaveText("View at Nile Parts");
    await row(page, "o-ai-oasis")
      .getByRole("link", { name: /View Oasis Parts Lab’s listing/ })
      .tap();
    await expect(page.locator("h1")).toHaveText(OASIS_TITLE);
    await expect(bar(page).getByRole("link")).toHaveText("View at Oasis Parts Lab");
    await expect(bar(page).getByRole("link")).toHaveAttribute("href", /oasis-parts-lab\.test/);
    await expect(bar(page)).toContainText("EGP 450");
    await expect(bar(page)).toContainText("checked 3 days ago");
    const thumb = page.locator("h1").locator("xpath=../../..").locator("img").first();
    await expect(thumb).toHaveAttribute("src", /oasis-1\.svg/);
    await noSidewaysScroll(page);
  });

  test("an out-of-stock shop's bar shows no price, as its button does", async ({ page }) => {
    await page.goto(`${URL}?shop=sinai-spares`);
    await expect(bar(page).getByRole("link")).toHaveText("View at Sinai Spares");
    await expect(bar(page).locator("[data-bar-stock]")).toHaveText("Out of stock");
    await expect(bar(page)).not.toContainText("EGP");
    // Picked in place rather than by link: the same.
    await page.goto(URL);
    await expect(bar(page)).toContainText("EGP 385");
    await page.locator("details[data-out-of-stock] summary").tap();
    await row(page, "o-ai-sinai")
      .getByRole("link", { name: /View Sinai Spares’s listing/ })
      .tap();
    await expect(bar(page).getByRole("link")).toHaveText("View at Sinai Spares");
    await expect(bar(page)).not.toContainText("EGP");
  });

  test("a tap opens the badge's tooltip, inside the screen", async ({ page }) => {
    await page.goto(URL);
    await row(page, "o-ai-volt").locator("[data-ai-badge]").tap();
    const tip = page.locator("[data-ai-tip]");
    await expect(tip).toBeVisible();
    const box = (await tip.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(PHONE.width);
    await page.locator("h1").tap();
    await expect(tip).toBeHidden();
    await noSidewaysScroll(page);
  });

  test("the new controls are 44px to a finger, and nothing scrolls sideways", async ({ page }) => {
    await page.goto(URL);
    for (const [name, control] of Object.entries({
      badge: row(page, "o-ai-volt").locator("[data-ai-badge]"),
      "view listing": row(page, "o-ai-volt").locator("[data-view-listing]"),
      "tell us": page.getByRole("button", { name: "tell us" }),
      tab: page.locator("label[data-details-tab]").first(),
    })) {
      expect(await tapHeight(control), name).toBeGreaterThanOrEqual(44);
    }
    await noSidewaysScroll(page);
    await page.setViewportSize({ width: 320, height: 700 });
    await noSidewaysScroll(page);
  });
});

test.describe("a linked shop view", () => {
  test("?shop= is rendered on the server, complete without JavaScript", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: PHONE });
    const page = await context.newPage();
    await page.goto(`${URL}?shop=volt-corner`);
    await expect(page.locator("h1")).toHaveText(VOLT_TITLE);
    await expect(row(page, "o-ai-volt")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[aria-current]")).toHaveCount(1);
    await expect(page.locator("#details-source-0")).toBeChecked();
    await expect(tab(page, /^Volt Corner/)).toBeChecked();
    await expect(page.locator("[data-details-source]:visible")).toHaveText(
      "From Volt Corner's listing",
    );
    await expect(bar(page).getByRole("link")).toHaveAttribute("href", /volt-corner\.test/);
    const thumb = page.locator("h1").locator("xpath=../../..").locator("img").first();
    await expect(thumb).toHaveAttribute("src", /volt-1\.svg/);
    // The tabs still switch the text without JavaScript, as before.
    await page
      .getByRole("radiogroup", { name: "What the shops say" })
      .locator("label", { hasText: "Oasis Parts Lab" })
      .click();
    await expect(page.locator("[data-details-source]:visible")).toHaveText(
      "From Oasis Parts Lab's listing",
    );
    // "View listing" is a link: without JavaScript it loads that shop's view.
    await row(page, "o-ai-nile").locator("[data-view-listing]").click();
    await expect(page).toHaveURL(/\?shop=nile-parts$/);
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);
    // Without JavaScript "tell us" is words, not a dead button.
    await expect(page.locator("[data-ai-note] button")).toHaveCount(0);
    await context.close();
  });

  test("?shop= on desktop: button and gallery", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto(`${URL}?shop=volt-corner`);
    await expect(primary(page)).toHaveText("EGP 410 at Volt Corner");
    await expect.poll(() => galleryIndex(page)).toBe(3);
  });

  test("an unknown shop falls back to the cheapest", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    const response = await page.goto(`${URL}?shop=no-such-shop`);
    expect(response?.status()).toBe(200);
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);
    await expect(row(page, "o-ai-nile")).toHaveAttribute("aria-current", "true");
    await context.close();
  });

  test("metadata stays the product's", async ({ page }) => {
    const head = async (path: string) => {
      await page.goto(path);
      return page.evaluate(() => {
        const meta = (selector: string) =>
          document.querySelector(selector)?.getAttribute("content") ?? null;
        return {
          title: document.title,
          canonical: document.querySelector('link[rel="canonical"]')?.getAttribute("href"),
          description: meta('meta[name="description"]'),
          ogTitle: meta('meta[property="og:title"]'),
          ogUrl: meta('meta[property="og:url"]'),
          ogImage: meta('meta[property="og:image"]'),
          twitterTitle: meta('meta[name="twitter:title"]'),
          jsonLd: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(
            (script) => script.textContent,
          ),
          crumbs: Array.from(document.querySelectorAll("nav[aria-label] a")).map(
            (a) => a.textContent,
          ),
        };
      });
    };
    const plain = await head(URL);
    const linked = await head(`${URL}?shop=volt-corner`);
    expect(linked).toEqual(plain);
    expect(plain.title).toBe(`${PRODUCT_TITLE} · makhzan`);
    expect(plain.canonical).toBe("https://makhzan.test/products/p-ai");
    expect(plain.jsonLd.join("")).toContain(PRODUCT_TITLE);
    expect(plain.jsonLd.join("")).not.toContain(VOLT_TITLE);
  });
});

test.describe("the representative listing", () => {
  test.use({ viewport: DESKTOP });

  // Owner decision (November 2026): a plain load picks the listing the
  // product's title comes from, so the h1 and <title> are one listing's.
  // On p-rep the cheapest in stock (Delta Bench) has no photo, so that
  // listing is Volt Corner's.
  const REP_URL = "/products/p-rep";

  test("a plain load picks it, not the cheapest", async ({ page }) => {
    await page.goto(REP_URL);
    await expect(page.locator("h1")).toHaveText(VOLT_TITLE);
    await expect(page).toHaveTitle(`${VOLT_TITLE} · makhzan`);
    await expect(row(page, "o-rep-volt")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[aria-current]")).toHaveCount(1);
    await expect(primary(page)).toHaveText("EGP 410 at Volt Corner");
    // The summary is still the product's: the range starts at the cheapest.
    await expect(page.locator("[data-summary] [data-price]").first()).toHaveText("EGP 380 – 410");
    expect(page.url()).not.toContain("shop=");
  });

  test("?shop= still picks that shop", async ({ page }) => {
    await page.goto(`${REP_URL}?shop=delta-bench`);
    await expect(page.locator("h1")).toHaveText("TB6600 Stepper Motor Driver Controller");
    await expect(row(page, "o-rep-delta")).toHaveAttribute("aria-current", "true");
    await expect(page).toHaveTitle(`${VOLT_TITLE} · makhzan`);
  });
});

test.describe("back and forward", () => {
  test.use({ viewport: DESKTOP });

  // The shop shown must always be the URL's: Next keeps the page as the
  // server first rendered it, and `?shop=` is rewritten in place, so a Back
  // onto the page restores a render for another shop under the new URL.
  const departments = (page: Page) =>
    page.locator("header").getByRole("link", { name: "Departments" }).first();

  test("a linked shop view, another shop picked, away and Back: the URL's shop", async ({
    page,
  }) => {
    await page.goto(`${URL}?shop=volt-corner`);
    await expect(page.locator("h1")).toHaveText(VOLT_TITLE);
    await row(page, "o-ai-oasis")
      .getByRole("link", { name: /View Oasis Parts Lab’s listing/ })
      .click();
    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);
    await expect(page.locator("h1")).toHaveText(OASIS_TITLE);

    await departments(page).click();
    await expect(page).toHaveURL(/\/departments$/);
    await page.goBack();

    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);
    await expect(page.locator("h1")).toHaveText(OASIS_TITLE);
    await expect(row(page, "o-ai-oasis")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[aria-current]")).toHaveCount(1);
    await expect(tab(page, /^Oasis Parts Lab/)).toBeChecked();
    await expect(primary(page)).toHaveText("EGP 450 at Oasis Parts Lab");

    // And forward and back again change nothing.
    await page.goForward();
    await expect(page).toHaveURL(/\/departments$/);
    await page.goBack();
    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);
    await expect(page.locator("h1")).toHaveText(OASIS_TITLE);
    await expect(row(page, "o-ai-oasis")).toHaveAttribute("aria-current", "true");
  });

  test("a URL that loses ?shop=: the plain load's pick, mounted and after Back", async ({
    page,
  }) => {
    await page.goto(`${URL}?shop=volt-corner`);
    await expect(page.locator("h1")).toHaveText(VOLT_TITLE);
    // A pick first, which also proves the page is hydrated (Next has taken
    // over history), as it is when a visitor picks.
    await row(page, "o-ai-oasis")
      .getByRole("link", { name: /View Oasis Parts Lab’s listing/ })
      .click();
    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);
    // Then the URL loses ?shop= in place, by a change the page did not make
    // itself (not a pick): the mounted view follows it to the plain load's
    // pick, and so does the page restored by Back below.
    await page.evaluate(() => window.history.replaceState(null, "", window.location.pathname));
    await expect(page).toHaveURL(/\/products\/p-ai$/);
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);

    await departments(page).click();
    await expect(page).toHaveURL(/\/departments$/);
    await page.goBack();

    await expect(page).toHaveURL(/\/products\/p-ai$/);
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);
    await expect(row(page, "o-ai-nile")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[aria-current]")).toHaveCount(1);
    await expect(primary(page)).toHaveText("EGP 385 at Nile Parts");
  });

  test("a plain load, a shop picked, away and Back: the picked shop", async ({ page }) => {
    await page.goto(URL);
    await expect(page.locator("h1")).toHaveText(NILE_TITLE);
    await row(page, "o-ai-oasis")
      .getByRole("link", { name: /View Oasis Parts Lab’s listing/ })
      .click();
    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);

    await departments(page).click();
    await expect(page).toHaveURL(/\/departments$/);
    await page.goBack();

    await expect(page).toHaveURL(/\?shop=oasis-parts-lab$/);
    await expect(page.locator("h1")).toHaveText(OASIS_TITLE);
    await expect(row(page, "o-ai-oasis")).toHaveAttribute("aria-current", "true");
    await expect(page.locator("[aria-current]")).toHaveCount(1);
    await expect(primary(page)).toHaveText("EGP 450 at Oasis Parts Lab");
  });
});
