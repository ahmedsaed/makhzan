import "@testing-library/jest-dom/vitest";
import { render, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultCard, ResultRow } from "@/components/result";
import { ShopLink } from "@/components/shop-link";
import type { SearchHit } from "@/lib/api";

const NOW = new Date("2026-11-06T12:00:00Z");

const hit: SearchHit = {
  id: "prod-1",
  domain: "electronics",
  part_number: "ESP32-WROOM-32",
  title_en: "ESP32 Development Board 30 pin (WIFI - Bluetooth)",
  title_ar: null,
  brand: null,
  category_slug: "dev-boards",
  category_ref: "electronics:dev-boards",
  category_name: "Dev boards",
  supplier_name: "Shop A",
  supplier_count: 3,
  offer_count: 4,
  min_price: 260,
  max_price: 400,
  currency: "EGP",
  in_stock: true,
  image: null,
  // 13 days before NOW.
  last_verified_at: NOW.getTime() / 1000 - 13 * 86_400,
};

function renderIn(Component: typeof ResultRow, value: SearchHit) {
  return render(
    <ul>
      <Component hit={value} now={NOW} />
    </ul>,
  );
}

describe.each([
  ["row", ResultRow],
  ["card", ResultCard],
] as const)("a result %s", (_, Component) => {
  it("shows title, price range, shops and freshness (rule C1)", () => {
    const { container } = renderIn(Component, hit);
    const item = within(container);
    expect(item.getByText(hit.title_en!)).toBeInTheDocument();
    expect(item.getByText("EGP 260 – 400")).toBeInTheDocument();
    expect(item.getByText("3 shops")).toBeInTheDocument();
    expect(item.getByText("checked 13 days ago")).toBeInTheDocument();
  });

  it("names the shop when there is only one", () => {
    const { container } = renderIn(Component, { ...hit, supplier_count: 1, max_price: 260 });
    const item = within(container);
    expect(item.getByText("Shop A")).toBeInTheDocument();
    expect(item.getByText("EGP 260")).toBeInTheDocument();
    expect(item.queryByText(/shops$/)).not.toBeInTheDocument();
  });

  it("on the shop's own page, leaves its name out but keeps the rest", () => {
    const { container } = render(
      <ul>
        <Component hit={{ ...hit, supplier_count: 1, max_price: 260 }} now={NOW} hideShop />
      </ul>,
    );
    const item = within(container);
    expect(item.queryByText("Shop A")).not.toBeInTheDocument();
    expect(item.queryByText("·")).not.toBeInTheDocument();
    expect(item.getByText("EGP 260")).toBeInTheDocument();
    expect(item.getByText("checked 13 days ago")).toBeInTheDocument();
  });

  it("on the shop's own page, still says when other shops sell it too", () => {
    const { container } = render(
      <ul>
        <Component hit={hit} now={NOW} hideShop />
      </ul>,
    );
    expect(within(container).getByText("3 shops")).toBeInTheDocument();
  });

  it("says 'Price on request' rather than a number when unpriced", () => {
    const { container } = renderIn(Component, { ...hit, min_price: null, max_price: null });
    expect(within(container).getByText("Price on request")).toBeInTheDocument();
  });

  it("links to the product page and nowhere else (rule P1)", () => {
    const { container } = renderIn(Component, hit);
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/products/prod-1");
  });

  it("credits a photo to the shop it comes from, which need not be the shop named", () => {
    const { container } = renderIn(Component, {
      ...hit,
      image: "https://shop-b.test/esp32.jpg",
      image_shop: { slug: "shop-b", name: "Shop B" },
    });
    const img = container.querySelector("img");
    expect(img).toHaveAttribute("alt", `${hit.title_en} — photo from Shop B`);
    // Still one link: the badge is not a way to the shop (P1).
    expect(container.querySelectorAll("a")).toHaveLength(1);
  });

  it("renders a photo without a credit when the hit predates image_shop", () => {
    const { container } = renderIn(Component, { ...hit, image: "https://shop-b.test/esp32.jpg" });
    expect(container.querySelector("img")).toHaveAttribute("alt", hit.title_en!);
    expect(container.querySelector("[data-photo-shop]")).toBeNull();
  });
});

describe("the photo's shop badge on results", () => {
  const pictured: SearchHit = {
    ...hit,
    image: "https://shop-b.test/esp32.jpg",
    image_shop: { slug: "shop-b", name: "Shop B" },
  };

  it("is drawn on a grid card's photo", () => {
    const { container } = renderIn(ResultCard, pictured);
    expect(container.querySelector("[data-photo-shop]")).toHaveTextContent("Shop B");
  });

  it("is left off a list row's 72px thumbnail, which credits the shop in alt and title", () => {
    const { container } = renderIn(ResultRow, pictured);
    expect(container.querySelector("[data-photo-shop]")).toBeNull();
    expect(container.querySelector("img")).toHaveAttribute("title", "Photo from Shop B");
  });

  it("is never drawn over the placeholder", () => {
    const { container } = renderIn(ResultCard, { ...pictured, image: null });
    expect(container.querySelector("[data-photo-shop]")).toBeNull();
  });
});

describe("a row's shop and freshness on a phone", () => {
  const meta = (value: SearchHit) =>
    renderIn(ResultRow, value).container.querySelector("[data-meta]")!;

  it("share a line, with a separator, while the price is fresh", () => {
    const line = meta({ ...hit, supplier_count: 1 });
    expect(line).toHaveAttribute("data-meta", "inline");
    expect(line.textContent).toBe("Shop A·checked 13 days ago");
  });

  it("stack with no separator when the stale badge would wrap", () => {
    const line = meta({
      ...hit,
      supplier_count: 1,
      last_verified_at: NOW.getTime() / 1000 - 74 * 86_400,
    });
    expect(line).toHaveAttribute("data-meta", "stacked");
    expect(line.textContent).not.toContain("·");
    expect(line).toHaveTextContent("Price may be out of date (74 days)");
  });
});

describe("row and card agree", () => {
  it("carry exactly the same text (rule C1)", () => {
    // Whitespace aside, switching views must not add or drop a fact.
    const text = (node: HTMLElement) =>
      [...node.querySelectorAll("span")]
        .filter((span) => span.children.length === 0)
        .map((span) => span.textContent?.trim())
        .filter((value) => value && value !== "·" && value !== hit.category_name)
        .sort();
    const row = renderIn(ResultRow, hit).container;
    const card = renderIn(ResultCard, hit).container;
    expect(text(card)).toEqual(text(row));
  });
});

describe("ShopLink (rule P4)", () => {
  it("tags, opens in a new tab and records the click", () => {
    const { getByRole } = render(
      <ShopLink href="https://shop-a.test/p/esp32?id=3" shop="shop-a">
        View
      </ShopLink>,
    );
    const link = getByRole("link", { name: "View" });
    expect(link).toHaveAttribute("href", "https://shop-a.test/p/esp32?id=3&ref=makhzan");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener");
    expect(link).toHaveAttribute("data-umami-event", "shop-click");
    expect(link).toHaveAttribute("data-umami-event-shop", "shop-a");
  });
});
