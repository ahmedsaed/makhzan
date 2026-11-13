import { expect, test, type Page } from "@playwright/test";

/**
 * "Report a problem" in a real browser: the button beside the title (variant
 * F of the approved mockup), the Base UI dialog it opens (focus trapped, Esc,
 * focus back on the button), every state of the form, phone and desktop, the
 * keyboard alone, and no layout shift. The stub API takes reports and signs
 * no real tokens (tests/e2e/stub-api.mjs); the API's own checks are tested in
 * apps/api. The refusals are set per test with page.route.
 *
 * Products are the stub's: `p-multi` has seven offers at three shops,
 * `p-single` one.
 */

const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1280, height: 900 };

const button = (page: Page) => page.getByRole("button", { name: "Report a problem" });
const dialog = (page: Page) => page.getByRole("dialog", { name: "Report a problem" });

async function open(page: Page, path = "/products/p-multi") {
  await page.goto(path);
  await button(page).click();
  await expect(dialog(page)).toBeVisible();
  return dialog(page);
}

test.describe("the button", () => {
  test("desktop: labelled, at the far right of the title's row", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/products/p-multi");
    const report = button(page);
    await expect(report).toBeVisible();
    await expect(report).toHaveText("Report a problem");
    expect(await report.evaluate((el) => el.tagName)).toBe("BUTTON");
    // One way in: no button on the offer rows, no email link under the contacts.
    await expect(page.getByRole("button", { name: /report/i })).toHaveCount(1);
    await expect(page.locator("[data-offer] button")).toHaveCount(0);

    const title = await page.locator("h1").boundingBox();
    const box = await report.boundingBox();
    const block = await page.locator("h1").evaluate((h1) => {
      const row = h1.parentElement!.getBoundingClientRect();
      return { right: row.right };
    });
    expect(title && box).toBeTruthy();
    // Beside the title, not under it, and pushed to the right end.
    expect(box!.y).toBeLessThan(title!.y + title!.height);
    expect(box!.x).toBeGreaterThan(title!.x + title!.width - 1);
    expect(Math.abs(box!.x + box!.width - block.right)).toBeLessThanOrEqual(1);
  });

  test("phone: a 44px flag with its name, and the title keeps its width", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto("/products/p-single");
    const report = button(page);
    await expect(report).toBeVisible();
    const box = await report.boundingBox();
    expect(Math.round(box!.width)).toBe(44);
    expect(Math.round(box!.height)).toBe(44);
    await expect(report.getByText("Report a problem")).toBeHidden();
    await expect(report).toHaveAccessibleName("Report a problem");
  });

  test("is drawn on the server, so nothing moves when the page wakes", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: DESKTOP });
    const still = await context.newPage();
    await still.goto("/products/p-multi");
    const before = await still.locator("[data-report-button]").boundingBox();
    const titleBefore = await still.locator("h1").boundingBox();
    await context.close();

    const page = await browser.newPage({ viewport: DESKTOP });
    await page.goto("/products/p-multi");
    await page.waitForLoadState("networkidle");
    expect(await page.locator("[data-report-button]").boundingBox()).toEqual(before);
    expect(await page.locator("h1").boundingBox()).toEqual(titleBefore);
    // And the browser saw no shift at all while it loaded.
    const shift = await page.evaluate(
      () =>
        new Promise<number>((resolve) => {
          let total = 0;
          new PerformanceObserver((list) => {
            for (const entry of list.getEntries() as (PerformanceEntry & { value: number })[])
              total += entry.value;
          }).observe({ type: "layout-shift", buffered: true });
          setTimeout(() => resolve(total), 300);
        }),
    );
    expect(shift).toBeLessThan(0.01);
    await page.close();
  });
});

test.describe("the dialog", () => {
  test.use({ viewport: DESKTOP });

  test("opens on its question, traps focus, and Esc gives focus back", async ({ page }) => {
    const titleBefore = await page
      .goto("/products/p-multi")
      .then(() => page.locator("h1").boundingBox());
    await button(page).click();
    const box = dialog(page);
    await expect(box).toBeVisible();
    await expect(box.getByRole("heading", { name: "What’s wrong?" })).toBeFocused();
    // Centred on a wide screen.
    const shape = await box.boundingBox();
    expect(Math.abs(shape!.x + shape!.width / 2 - DESKTOP.width / 2)).toBeLessThan(2);
    // Opening it moves nothing behind it.
    expect(await page.locator("h1").boundingBox()).toEqual(titleBefore);

    // Past the last control, Tab wraps to the first (the trap's guards move
    // focus a moment after the key), and Shift+Tab the other way.
    const inside = () =>
      page.evaluate(() => Boolean(document.activeElement?.closest("[data-report-dialog]")));
    const names: string[] = [];
    for (let i = 0; i < 9; i++) {
      await page.keyboard.press("Tab");
      await expect.poll(inside, { message: `Tab ${i + 1} stays inside` }).toBe(true);
      names.push(
        await page.evaluate(
          () =>
            document.activeElement?.getAttribute("aria-label") ??
            document.activeElement?.textContent?.trim() ??
            "",
        ),
      );
    }
    expect(names.slice(0, 5)).toEqual(["", "Cancel", "Continue", "Close", ""]);
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Shift+Tab");
    await expect.poll(inside).toBe(true);

    await page.keyboard.press("Escape");
    await expect(box).toBeHidden();
    await expect(button(page)).toBeFocused();
  });

  test("the close button and the backdrop close it too", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("button", { name: "Close" }).click();
    await expect(box).toBeHidden();
    await expect(button(page)).toBeFocused();
    await button(page).click();
    await page.mouse.click(10, 10);
    await expect(dialog(page)).toBeHidden();
  });

  test("the honeypot is never reached by Tab", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /Wrong category/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    const names: string[] = [];
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      names.push(await page.evaluate(() => (document.activeElement as HTMLInputElement).name));
    }
    expect(names).not.toContain("website");
    await expect(box.locator('input[name="website"]')).not.toBeInViewport();
  });

  test("dark mode uses the dark tokens", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    const box = await open(page);
    const colours = await box.evaluate((el) => {
      const style = getComputedStyle(el);
      return { background: style.backgroundColor, text: style.color };
    });
    // surface and ink in dark (docs/DESIGN.md).
    expect(colours).toEqual({ background: "rgb(27, 29, 33)", text: "rgb(236, 236, 234)" });
  });
});

test.describe("every state", () => {
  test.use({ viewport: DESKTOP });

  test("step 1 refuses to go on without a reason", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("button", { name: "Continue" }).click();
    await expect(box.getByText("Choose what’s wrong to continue.")).toBeVisible();
    await expect(box.getByRole("radio").first()).toBeFocused();
  });

  test("a one-shop page has no 'offers aren't the same'", async ({ page }) => {
    const box = await open(page, "/products/p-single");
    await expect(box.getByRole("radio")).toHaveCount(6);
    await expect(box.getByRole("radio", { name: /aren’t the same/ })).toHaveCount(0);
  });

  test("offers aren't the same: every offer to tick, then sent and thanked", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /aren’t the same/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await expect(box.getByText("Step 2 of 2")).toBeVisible();
    // All seven, out of stock included.
    await expect(box.getByRole("checkbox")).toHaveCount(7);
    await expect(box.getByText(/old stock/)).toBeVisible();
    await box.getByRole("button", { name: "Send report" }).click();
    await expect(
      box.getByText("Tick at least one offer that is a different product."),
    ).toBeVisible();

    await box.getByRole("checkbox", { name: /38-Pin – Micro USB/ }).check();
    await box.getByLabel(/Email/).fill("buyer@example.com");
    const request = page.waitForRequest((r) => r.url().endsWith("/api/reports"));
    await box.getByRole("button", { name: "Send report" }).click();
    const body = (await request).postDataJSON();
    expect(body).toMatchObject({
      product_id: "p-multi",
      reason: "offers_not_same",
      offer_ids: ["o-m5"],
      email: "buyer@example.com",
      website: "",
    });
    // The opened-at token the API signed when the dialog opened (the stub's).
    expect(body.token).toBe("stub-token");
    expect(body).not.toHaveProperty("elapsed_ms");
    const thanks = box.getByRole("status");
    await expect(thanks).toContainText("Thanks — we review every report");
    await expect(thanks).toContainText("We’ll reply to buyer@example.com");
    await expect(thanks).toContainText("Report R-101");
    await expect(box.getByRole("heading", { name: /Thanks/ })).toBeFocused();
  });

  test("wrong price or stock", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /Wrong price or stock/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await box.getByRole("button", { name: "Send report" }).click();
    await expect(box.getByText("Choose the offer that’s wrong.")).toBeVisible();
    await expect(box.getByText("Choose price or stock.")).toBeVisible();
    await box.getByRole("radio", { name: /with CP2102 Type-C/ }).check();
    await box.getByRole("radio", { name: "The price" }).check();
    await box.getByLabel(/Price on the shop’s site/).fill("310");
    const request = page.waitForRequest((r) => r.url().endsWith("/api/reports"));
    await box.getByRole("button", { name: "Send report" }).click();
    expect((await request).postDataJSON()).toMatchObject({
      reason: "wrong_price_stock",
      offer_ids: ["o-m2"],
      field: "price",
      correct_value: "EGP 310",
    });
    await expect(box.getByRole("status")).toContainText("You didn’t leave an email");
  });

  test("wrong category shows where it is filed now", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /Wrong category/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await expect(box.getByText("Filed under now")).toBeVisible();
    await expect(box.getByText(/Integrated Circuits/)).toBeVisible();
  });

  test("wrong details and contact details ask which shop", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /Wrong details/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await expect(box.getByLabel(/From which shop’s listing/)).toBeVisible();
    await box.getByRole("button", { name: "Back" }).click();
    await box.getByRole("radio", { name: /contact details/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await box.getByRole("button", { name: "Send report" }).click();
    await expect(box.getByText("Choose the shop.")).toBeVisible();
    await expect(box.getByLabel("Which shop?")).toBeFocused();
  });

  test("the same as another product: search, pick, send", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /same as another/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    const combo = box.getByRole("combobox");
    await combo.fill("ESP32");
    await expect(box.getByRole("option").first()).toBeVisible();
    await page.keyboard.press("ArrowDown");
    // Esc closes the list and leaves the dialog open.
    await page.keyboard.press("Escape");
    await expect(box).toBeVisible();
    await expect(combo).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(box.locator("[data-report-picked]")).toContainText("ESP32-WROOM-32 DevKit V1");
    const request = page.waitForRequest((r) => r.url().endsWith("/api/reports"));
    await box.getByRole("button", { name: "Send report" }).click();
    expect((await request).postDataJSON()).toMatchObject({
      reason: "same_as_other",
      other_product_id: "prod-1",
    });
  });

  test("something else needs words", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /Something else/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await box.getByRole("button", { name: "Send report" }).click();
    await expect(box.getByText("Tell us what’s wrong, in a few words.")).toBeVisible();
    await expect(box.getByLabel(/What’s wrong\?/)).toBeFocused();
  });

  test("sending, then not sent: nothing is lost", async ({ page }) => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/reports", async (route) => {
      await held;
      await route.fulfill({ status: 500, body: "{}" });
    });
    const box = await open(page);
    await box.getByRole("radio", { name: /Wrong category/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await box.getByLabel(/Anything else/).fill("It is a dev board, not an IC.");
    await box.getByRole("button", { name: "Send report" }).click();
    await expect(box.getByRole("button", { name: "Sending…" })).toBeVisible();
    await expect(box.getByLabel(/Anything else/)).toBeDisabled();
    release();
    const alert = box.getByRole("alert");
    await expect(alert).toContainText("Your report wasn’t sent.");
    await expect(alert.getByRole("link", { name: "email it to us" })).toHaveAttribute(
      "href",
      /^mailto:crawler@makhzan\.merope\.dev\?subject=Report%20a%20problem/,
    );
    await expect(box.getByLabel(/Anything else/)).toHaveValue("It is a dev board, not an IC.");
  });

  test("too many reports", async ({ page }) => {
    await page.route("**/api/reports", (route) =>
      route.fulfill({
        status: 429,
        contentType: "application/json",
        headers: { "retry-after": "2400" },
        body: JSON.stringify({ detail: { limit: "hour", count: 5, retry_after_minutes: 40 } }),
      }),
    );
    const box = await open(page);
    await box.getByRole("radio", { name: /Something else/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    await box.getByLabel(/What’s wrong\?/).fill("The page title has a typo.");
    await box.getByRole("button", { name: "Send report" }).click();
    const alert = box.getByRole("alert");
    await expect(alert).toContainText("You’ve sent 5 reports in the last hour.");
    await expect(alert).toContainText("please wait about 40 minutes");
    await expect(box.getByLabel(/What’s wrong\?/)).toHaveValue("The page title has a typo.");
  });

  test("the privacy note links the policy", async ({ page }) => {
    const box = await open(page);
    await box.getByRole("radio", { name: /Wrong category/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    const note = box.locator("[data-report-privacy]");
    await expect(note).toContainText("deleted 90 days after you send it");
    await expect(note.getByRole("link", { name: /Privacy policy/ })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: PHONE });

  test("a sheet from the bottom, the keyboard alone, and nothing sideways", async ({ page }) => {
    await page.goto("/products/p-multi");
    await button(page).focus();
    await page.keyboard.press("Enter");
    const box = dialog(page);
    await expect(box).toBeVisible();
    const shape = await box.boundingBox();
    expect(Math.round(shape!.x)).toBe(0);
    expect(Math.round(shape!.width)).toBe(PHONE.width);
    expect(Math.round(shape!.y + shape!.height)).toBe(PHONE.height);

    // Arrow keys move between reasons; Enter submits the step.
    await expect(box.getByRole("heading", { name: "What’s wrong?" })).toBeFocused();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Space");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(box.getByRole("radio", { name: /Wrong category/ })).toBeChecked();
    await page.keyboard.press("Enter");
    await expect(box.getByRole("heading", { name: "Wrong category" })).toBeFocused();
    await page.keyboard.press("Tab");
    await page.keyboard.type("Dev boards");
    await page.keyboard.press("Enter");
    await expect(box.getByRole("status")).toContainText("Thanks");

    // Nothing scrolls sideways, even at 320px with the sheet open.
    await page.setViewportSize({ width: 320, height: 640 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    const sheet = await box.boundingBox();
    expect(sheet!.width).toBeLessThanOrEqual(320);
  });

  test("controls inside are 44px to a finger", async ({ page }) => {
    const box = await open(page);
    for (const control of [
      box.getByRole("button", { name: "Close" }),
      box.getByRole("button", { name: "Continue" }),
      box.getByRole("button", { name: "Cancel" }),
    ]) {
      expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    }
    await box.getByRole("radio", { name: /Wrong price/ }).check();
    await box.getByRole("button", { name: "Continue" }).click();
    const chip = box.getByText("The price", { exact: true });
    expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  });
});

test.describe("the privacy page", () => {
  test("exists, says what is kept, and is in every footer", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("contentinfo").getByRole("link", { name: "Privacy" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByRole("heading", { level: 1, name: "Privacy" })).toBeVisible();
    await expect(page.locator("[data-retention]")).toContainText(
      "Deleted 90 days after you send it.",
    );
    await expect(page.locator("[data-retention]")).toContainText("Deleted after 24 hours");
    await expect(page.getByText(/Law No\. 151 of 2020/)).toBeVisible();
    // Both processors, plainly (the owner's decision); /how-we-crawl stays
    // free of the name (tests/e2e/crawler-identity.spec.ts).
    await expect(page.getByText(/passes through Cloudflare/)).toBeVisible();
    await expect(page.getByText(/access log of the requests it receives/)).toBeVisible();
  });

  test("nothing scrolls sideways on a phone", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await page.goto("/privacy");
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
  });
});
