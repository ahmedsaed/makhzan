/**
 * Layout B's navigation (docs/DESIGN.md, "Department and category"): the
 * department's tree as the desktop sidebar and the phone sheet, the phone's
 * Browse pill, and the toolbar's Price chip.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BrowseSheet } from "@/components/browse-sheet";
import { BrowseTree } from "@/components/browse-tree";
import { PriceChip } from "@/components/price-chip";
import type { Category } from "@/lib/api";

const cat = (
  domain: string,
  slug: string,
  name_en: string,
  parent: string | null,
  count: number,
): Category => ({
  ref: `${domain}:${slug}`,
  domain,
  slug,
  name_en,
  name_ar: null,
  parent: parent ? `${domain}:${parent}` : null,
  count,
});

const ELECTRONICS = [
  cat("electronics", "components", "Components", null, 0),
  cat("electronics", "resistors", "Resistors", "components", 2704),
  cat("electronics", "capacitors", "Capacitors", "components", 1351),
  cat("electronics", "empty", "Empty", "components", 0),
  cat("electronics", "power", "Power", null, 0),
  cat("electronics", "batteries", "Batteries & Chargers", "power", 1936),
  cat("electronics", "solar", "Solar", "power", 276),
  cat("electronics", "other", "Accessories & Other", null, 0),
  cat("electronics", "accessories", "Accessories", "other", 1202),
];

const SEALS = [
  cat("seals-bearings", "seals", "Seals & Gaskets", null, 0),
  cat("seals-bearings", "o-rings", "O-Rings", "seals", 400),
  cat("seals-bearings", "gaskets", "Gaskets", "seals", 90),
  cat("seals-bearings", "transmission", "Bearings & Transmission", null, 0),
  cat("seals-bearings", "bearings", "Bearings", "transmission", 300),
  cat("seals-bearings", "couplings", "Couplings", "transmission", 40),
];

function tree(selected: string | null, categories = ELECTRONICS, department = "electronics") {
  return render(
    <BrowseTree
      department={department}
      categories={categories}
      selected={selected}
      density="sidebar"
    />,
  );
}

describe("the browse tree", () => {
  it("starts with the whole department, current on its own page", () => {
    tree(null);
    const all = screen.getByRole("link", { name: /^All of Electronics/ });
    expect(all).toHaveAttribute("href", "/departments/electronics");
    expect(all).toHaveAttribute("aria-current", "page");
    expect(all).toHaveTextContent("7,469");
  });

  it("lists groups by size with their counts, collapsed when none is current", () => {
    tree(null);
    const groups = document.querySelectorAll("[data-tree-group]");
    expect([...groups].map((g) => g.textContent)).toEqual([
      "Components4,055",
      "Power2,212",
      "Accessories & Other1,202",
    ]);
    for (const list of document.querySelectorAll("[data-tree-node] > ul")) {
      expect(list).toHaveAttribute("hidden");
    }
  });

  it("expands the current group and marks the current category, outlined and bold", () => {
    tree("electronics:resistors");
    const components = document.querySelector("[data-tree-node='electronics:components']")!;
    expect(components.querySelector("ul")).not.toHaveAttribute("hidden");
    const here = screen.getByRole("link", { name: /^Resistors/ });
    expect(here).toHaveAttribute("aria-current", "page");
    expect(here).toHaveAttribute("href", "/departments/electronics/resistors");
    expect(here.className).toMatch(/outline-chip-on/);
    expect(here.className).toMatch(/font-semibold/);
    // Never a fill.
    expect(here.className).not.toMatch(/\bbg-chip-on\b/);
    // Other groups stay collapsed; empty categories are left out.
    const power = document.querySelector("[data-tree-node='electronics:power']")!;
    expect(power.querySelector("ul")).toHaveAttribute("hidden");
    expect(screen.queryByRole("link", { name: /^Empty/ })).toBeNull();
  });

  it("marks a group as current on its own page", () => {
    tree("electronics:power");
    const power = document.querySelector("[data-tree-group='electronics:power']")!;
    expect(power).toHaveAttribute("aria-current", "page");
    expect(power).toHaveAttribute("href", "/departments/electronics/power");
  });

  it("expands another group in place", () => {
    tree("electronics:resistors");
    const toggle = screen.getByRole("button", { name: "Subcategories of Power" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAccessibleName("Subcategories of Power");
    const list = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(list).not.toHaveAttribute("hidden");
    expect(within(list).getByRole("link", { name: /^Solar/ })).toHaveTextContent("276");
  });

  it("links a group of one category straight to that category", () => {
    tree(null);
    const other = document.querySelector("[data-tree-group='electronics:other']")!;
    expect(other).toHaveAttribute("href", "/departments/electronics/accessories");
    expect(
      screen.queryByRole("button", { name: /Subcategories of Accessories & Other/ }),
    ).toBeNull();
  });

  it("keeps a group of one category when the group holds products of its own", () => {
    tree(null, [
      ...ELECTRONICS.slice(0, 7),
      cat("electronics", "other", "Accessories & Other", null, 50),
      ELECTRONICS[8],
    ]);
    const other = document.querySelector("[data-tree-group='electronics:other']")!;
    expect(other).toHaveAttribute("href", "/departments/electronics/other");
  });

  it("draws Electronics' icons, keyed by ref", () => {
    tree("electronics:resistors");
    expect(document.querySelector("svg[data-icon='electronics:components']")).not.toBeNull();
    expect(document.querySelector("svg[data-icon='electronics:resistors']")).not.toBeNull();
  });

  it("leaves an undrawn department's categories plain, its groups with the department icon", () => {
    tree("seals-bearings:o-rings", SEALS, "seals-bearings");
    expect(document.querySelectorAll("[data-tree-category] svg")).toHaveLength(0);
    const groups = document.querySelectorAll("[data-tree-group]");
    for (const group of groups) {
      const icon = group.querySelector("svg");
      expect(icon).not.toBeNull();
      expect(icon).not.toHaveAttribute("data-icon");
    }
  });

  it("uses finger-sized rows in the sheet (S4)", () => {
    render(
      <BrowseTree
        department="electronics"
        categories={ELECTRONICS}
        selected="electronics:resistors"
        density="sheet"
      />,
    );
    expect(screen.getByRole("link", { name: /^Resistors/ }).className).toMatch(/min-h-11/);
    expect(screen.getByRole("button", { name: /Subcategories of Power/ }).className).toMatch(
      /size-11/,
    );
  });
});

describe("the phone's Browse pill and sheet", () => {
  function sheet() {
    return render(
      <BrowseSheet place="Resistors" title="Browse Electronics">
        <BrowseTree
          department="electronics"
          categories={ELECTRONICS}
          selected="electronics:resistors"
          density="sheet"
        />
      </BrowseSheet>,
    );
  }

  it("names where the page is, and leads to the tree without JavaScript", () => {
    sheet();
    const pill = document.querySelector("[data-browse-pill]")!;
    expect(pill).toHaveTextContent("Resistors· Browse");
    expect(pill).toHaveAttribute("href", "#browse-tree");
    expect(pill).toHaveAttribute("aria-haspopup", "dialog");
  });

  it("is a dialog named by its heading", () => {
    sheet();
    const dialog = document.querySelector("dialog[data-browse-sheet]")!;
    const heading = document.getElementById(dialog.getAttribute("aria-labelledby")!)!;
    expect(heading).toHaveTextContent("Browse Electronics");
    expect(dialog.querySelector("[aria-current='page']")).toHaveTextContent("Resistors");
  });
});

describe("the toolbar's Price chip", () => {
  it("is a GET form that carries the page's other parameters", () => {
    render(
      <PriceChip
        action="/departments/electronics"
        hidden={{ sort: "price_asc", in_stock: "all" }}
        clearHref="/departments/electronics?sort=price_asc&in_stock=all"
      />,
    );
    expect(screen.getByText("Price")).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Price, EGP" });
    expect(form).toHaveAttribute("action", "/departments/electronics");
    expect(form).toHaveAttribute("method", "get");
    expect(form.querySelector("input[name=sort]")).toHaveValue("price_asc");
    expect(within(form).getByLabelText("Min, EGP")).toHaveAttribute("name", "min_price");
    expect(within(form).getByLabelText("Max, EGP")).toHaveAttribute("name", "max_price");
  });

  it("names the price once one is set", () => {
    render(
      <PriceChip
        action="/x"
        hidden={{}}
        min={100}
        max={500}
        label="EGP 100 – 500"
        clearHref="/x"
      />,
    );
    expect(document.querySelector("summary")).toHaveTextContent("EGP 100 – 500");
    expect(screen.getByLabelText("Min, EGP")).toHaveValue(100);
  });
});
