import { expect, test, type Page } from "@playwright/test";

/**
 * The structured data each page type emits, against the stub, and that the
 * product markup states the price the page shows: Google penalises markup
 * that does not match what a reader sees. Products are the stub's fixtures
 * (tests/e2e/fixtures/product.mjs and phase2.mjs); shops are shops.mjs.
 */

const SITE = "https://makhzan.test";
const DESKTOP = { width: 1280, height: 900 };

type Node = Record<string, unknown> & { "@type"?: string };

/** Every JSON-LD node on the page, `@graph`s and arrays flattened. */
async function nodes(page: Page): Promise<Node[]> {
  const blocks: unknown[] = await page
    .locator('script[type="application/ld+json"]')
    .evaluateAll((els) => els.map((el) => JSON.parse(el.textContent ?? "null")));
  return blocks.flatMap((block) => {
    const list = Array.isArray(block) ? block : [block];
    return list.flatMap((item) => ((item as Node)["@graph"] as Node[]) ?? [item as Node]);
  });
}

async function nodeOf(page: Page, type: string): Promise<Node | undefined> {
  return (await nodes(page)).find((node) => node["@type"] === type);
}

/** "EGP 0.15 – 2" → [0.15, 2]; "EGP 850" → [850, 850]. */
function range(text: string): [number, number] {
  const numbers = text
    .replace(/EGP/g, "")
    .split("–")
    .map((part) => Number(part.replace(/[,\s]/g, "")));
  return [numbers[0], numbers[numbers.length - 1]];
}

test.use({ viewport: DESKTOP });

test.describe("product", () => {
  for (const [id, where] of [
    ["p2-mixedmin", "[data-summary]"],
    ["p2-somepor", "[data-summary]"],
    ["p2-volume", "[data-summary]"],
    ["p2-cheapopt", "[data-summary]"],
    ["p-multi", "[data-summary]"],
    ["p-oos", "[data-summary]"],
    ["p2-options", "[data-buy]"],
    ["p2-minorder", "[data-buy]"],
  ] as const) {
    test(`${id}: the AggregateOffer is the price range the page shows`, async ({ page }) => {
      await page.goto(`/products/${id}`);
      const shown = await page.locator(`${where} [data-price]`).first().textContent();
      const product = await nodeOf(page, "Product");
      const offers = product?.offers as Node;
      expect(offers["@type"]).toBe("AggregateOffer");
      expect([offers.lowPrice, offers.highPrice]).toEqual(range(shown ?? ""));
      expect(offers.priceCurrency).toBe("EGP");
      expect(JSON.stringify(product)).not.toMatch(/"@type":"Offer"/);
    });
  }

  test("several shops: counts the offers the summary counts", async ({ page }) => {
    await page.goto("/products/p2-mixedmin");
    const text = await page.locator("[data-summary-text]").textContent();
    const offers = (await nodeOf(page, "Product"))?.offers as Node;
    expect(text).toContain(`${offers.offerCount} offers`);
    // The lowest needs 10, another sells one: no minimum on the aggregate.
    expect(offers).not.toHaveProperty("eligibleQuantity");
  });

  test("one shop with a minimum: the price of one, and the minimum", async ({ page }) => {
    await page.goto("/products/p2-minorder");
    const offers = (await nodeOf(page, "Product"))?.offers as Node;
    expect(offers).toMatchObject({
      lowPrice: 0.15,
      highPrice: 0.15,
      offerCount: 1,
      availability: "https://schema.org/InStock",
      eligibleQuantity: { "@type": "QuantitativeValue", minValue: 10 },
    });
  });

  test("every shop out of stock says so", async ({ page }) => {
    await page.goto("/products/p-oos");
    const offers = (await nodeOf(page, "Product"))?.offers as Node;
    expect(offers.availability).toBe("https://schema.org/OutOfStock");
  });

  // No price to state: a Product without offers would be an invalid item.
  test("price on request only: no Product markup, never a price of zero", async ({ page }) => {
    for (const id of ["p2-por", "p2-allpor"]) {
      await page.goto(`/products/${id}`);
      await expect(page.locator("h1")).toBeVisible();
      expect(await nodeOf(page, "Product"), id).toBeUndefined();
      expect(await nodeOf(page, "BreadcrumbList"), id).toBeTruthy();
    }
  });

  // p-single's one offer was checked 74 days ago: the page warns its price
  // may have changed, and markup cannot carry that.
  test("every offer out of date: no Product markup", async ({ page }) => {
    await page.goto("/products/p-single");
    await expect(page.locator("[data-buy] [data-price]").first()).toBeVisible();
    expect(await nodeOf(page, "Product")).toBeUndefined();
  });

  test("brand, and what one shop says the part fits", async ({ page }) => {
    await page.goto("/products/p2-badges");
    const product = await nodeOf(page, "Product");
    const fits = product?.isAccessoryOrSparePartFor as Node[];
    expect(fits[0]).toEqual({ "@type": "Product", name: "ELEGOO Mars 4 Ultra" });
    await page.goto("/products/p-multi");
    expect((await nodeOf(page, "Product"))?.brand).toBeUndefined();
  });

  test("two shops' differing fits are not merged; no mpn no shop states", async ({ page }) => {
    await page.goto("/products/p2-fits");
    const product = await nodeOf(page, "Product");
    expect(product).not.toHaveProperty("isAccessoryOrSparePartFor");
    // "MK8" is makhzan's, read from the titles; no shop states it.
    expect(product).not.toHaveProperty("mpn");
  });

  test("mpn is the part number a shop states", async ({ page }) => {
    await page.goto("/products/p2-minorder");
    expect((await nodeOf(page, "Product"))?.mpn).toBe("FRC0603F6803TS");
    // Two shops state different numbers: none.
    await page.goto("/products/p2-mfrs");
    expect(await nodeOf(page, "Product")).not.toHaveProperty("mpn");
  });

  // Noindex, and nothing on it is for sale: no Product markup at all, so no
  // last-seen price can read as a current offer.
  test("a withdrawn product has no Product markup", async ({ page }) => {
    await page.goto("/products/p-gone");
    await expect(page.locator("h1")).toBeVisible();
    expect(await nodeOf(page, "Product")).toBeUndefined();
  });
});

test.describe("shop", () => {
  test("a shop with every detail is a Store on a directory page", async ({ page }) => {
    await page.goto("/shops/shop-a");
    const webPage = await nodeOf(page, "WebPage");
    const store = await nodeOf(page, "Store");
    expect(webPage).toMatchObject({
      url: `${SITE}/shops/shop-a`,
      about: { "@id": store?.["@id"] },
      mainEntity: { "@id": store?.["@id"] },
      isPartOf: { "@id": `${SITE}/#website` },
    });
    expect(store).toMatchObject({
      name: "Shop A",
      // The shop's own site; makhzan's page is the WebPage about it.
      url: "https://www.shop-a.test/",
      telephone: "+20223456789",
      email: "sales@shop-a.test",
      hasMap: "https://maps.app.goo.gl/shopA",
      address: {
        "@type": "PostalAddress",
        streetAddress: "12 Example Street, 2nd floor, Bab El Louk",
        addressLocality: "Cairo",
        addressRegion: "Cairo",
        addressCountry: "EG",
      },
      subOrganization: [{ "@type": "Store", name: "Giza branch" }],
    });
    expect(store).not.toHaveProperty("sameAs");
    const hours = store?.openingHoursSpecification as Node[];
    expect(hours[0]).toMatchObject({ opens: "10:00", closes: "22:00" });
    expect(hours[0].dayOfWeek).toHaveLength(6);
    expect(hours[0].dayOfWeek).not.toContain("https://schema.org/Friday");
    // Friday, which no line names, is closed, as the page says.
    expect(hours[1]).toMatchObject({
      dayOfWeek: ["https://schema.org/Friday"],
      opens: "00:00",
      closes: "00:00",
    });
  });

  test("a shop with only an address claims nothing else", async ({ page }) => {
    await page.goto("/shops/stale-shop");
    const store = await nodeOf(page, "Store");
    expect(store?.address).toEqual({
      "@type": "PostalAddress",
      streetAddress: "31 شارع المثال",
      addressCountry: "EG",
    });
    for (const key of ["telephone", "email", "openingHoursSpecification", "hasMap"]) {
      expect(store, key).not.toHaveProperty(key);
    }
  });
});
