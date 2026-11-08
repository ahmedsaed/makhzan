import { expect, test } from "@playwright/test";

/**
 * The background pattern (components/background-pattern.tsx): decoration that
 * must stay out of the way. Hidden from assistive technology, never fixed to
 * the viewport, behind the content, and drawn from a tile that is served.
 */

test("the pattern is decoration behind the page, and scrolls away with it", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");

  const layer = page.locator("[data-bg-pattern]");
  await expect(layer).toHaveCount(1);
  await expect(layer).toHaveAttribute("aria-hidden", "true");

  const style = await layer.evaluate((el) => {
    const outer = getComputedStyle(el);
    const inner = getComputedStyle(el.firstElementChild!);
    return {
      position: outer.position,
      innerPosition: inner.position,
      zIndex: Number(outer.zIndex),
      pointerEvents: outer.pointerEvents,
      mask: inner.maskImage || inner.getPropertyValue("-webkit-mask-image"),
    };
  });
  expect(style.position).toBe("absolute");
  expect(style.innerPosition).toBe("absolute");
  expect(style.zIndex).toBeLessThan(0);
  expect(style.pointerEvents).toBe("none");
  expect(style.mask).toContain("pattern-wide.svg");

  // The hero headline is what is painted at its own centre: the pattern is
  // behind it, not over it. (The layer ignores pointer events, so the check
  // asks what is painted on top, which is the headline or its text.)
  const headline = page.getByRole("heading", { level: 1 });
  const onTop = await headline.evaluate((h1) => {
    const box = h1.getBoundingClientRect();
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    return hit !== null && h1.contains(hit);
  });
  expect(onTop).toBe(true);

  // Not fixed: scrolling moves it up with the page.
  const before = (await layer.boundingBox())!.y;
  await page.evaluate(() => window.scrollTo(0, 600));
  await expect.poll(async () => (await layer.boundingBox())!.y).toBeLessThan(before - 500);

  const tile = await page.request.get("/pattern-wide.svg");
  expect(tile.ok()).toBe(true);
  expect(await tile.text()).toContain("<symbol");
});

test("phones get the sparser tile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  const mask = await page
    .locator("[data-bg-pattern] > div")
    .evaluate((el) => getComputedStyle(el).maskImage);
  expect(mask).toContain("pattern-narrow.svg");
});
