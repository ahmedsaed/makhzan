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

const UNDRAWN = [
  cat("undrawn-dept", "seals", "Seals & Gaskets", null, 0),
  cat("undrawn-dept", "o-rings", "O-Rings", "seals", 400),
  cat("undrawn-dept", "gaskets", "Gaskets", "seals", 90),
  cat("undrawn-dept", "transmission", "Bearings & Transmission", null, 0),
  cat("undrawn-dept", "bearings", "Bearings", "transmission", 300),
  cat("undrawn-dept", "couplings", "Couplings", "transmission", 40),
];

/** A group's categories: the region its control names. */
function regionOf(node: Element): HTMLElement {
  const control = node.querySelector("button[aria-controls]")!;
  return document.getElementById(control.getAttribute("aria-controls")!)!;
}

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
    const lists = document.querySelectorAll("[data-tree-node] > ul");
    expect(lists.length).toBeGreaterThan(0);
    for (const list of lists) expect(list).toHaveAttribute("hidden");
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
    tree("undrawn-dept:o-rings", UNDRAWN, "undrawn-dept");
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

describe("the sheet's tree (option A of the sheet-motion mockup)", () => {
  function sheetTree(selected: string | null, categories = ELECTRONICS) {
    return render(
      <BrowseTree
        department="electronics"
        categories={categories}
        selected={selected}
        density="sheet"
      />,
    );
  }

  it("makes a group two separate tinted buttons, its name and a funnel", () => {
    sheetTree("electronics:resistors");
    const node = document.querySelector("[data-tree-node='electronics:power']")!;
    const name = node.querySelector("[data-tree-group]")!;
    const funnel = node.querySelector("button[data-funnel]")!;
    expect(name.tagName).toBe("A");
    expect(funnel.tagName).toBe("BUTTON");
    // Separate elements, neither inside the other, 6px apart with no divider.
    expect(name.contains(funnel) || funnel.contains(name)).toBe(false);
    expect(funnel.parentElement!.className).toMatch(/\bgap-1\.5\b/);
    for (const el of [name, funnel]) {
      expect(el.className).toMatch(/\bbg-tint\b/);
      expect(el.className).toMatch(/\brounded-md\b/);
    }
    expect(name.className).toMatch(/\bmin-h-11\b/);
    expect(funnel.className).toMatch(/\bsize-11\b/);
    expect(funnel.querySelector("svg[data-icon='funnel']")).not.toBeNull();
    expect(funnel).toHaveAccessibleName("Subcategories of Power");
    expect(funnel).toHaveAttribute("aria-expanded", "false");
  });

  it("fills the funnel solid while its group is open", () => {
    sheetTree("electronics:resistors");
    const funnel = (ref: string) =>
      document.querySelector(`[data-tree-node='${ref}'] button[data-funnel]`)!;
    expect(funnel("electronics:components")).toHaveAttribute("aria-expanded", "true");
    expect(funnel("electronics:components").className).toMatch(/\bbg-chip-on\b/);
    expect(funnel("electronics:power").className).not.toMatch(/\bbg-chip-on\b/);
    fireEvent.click(funnel("electronics:power"));
    expect(funnel("electronics:power").className).toMatch(/\bbg-chip-on\b/);
  });

  it("keeps a closed group's categories in the page, inert, folded by grid rows", () => {
    sheetTree("electronics:resistors");
    const power = document.querySelector("[data-tree-node='electronics:power']")!;
    const fold = regionOf(power);
    expect(fold).toHaveAttribute("data-fold");
    expect(fold.className).toMatch(/grid-rows-\[0fr\]/);
    expect(fold.className).toMatch(/transition-\[grid-template-rows\]/);
    // Crawlable: the links are there, only unreachable while folded.
    expect(fold.querySelector("a[href='/departments/electronics/solar']")).not.toBeNull();
    expect(fold.firstElementChild).toHaveAttribute("inert");
    fireEvent.click(power.querySelector("button[data-funnel]")!);
    expect(fold.className).toMatch(/grid-rows-\[1fr\]/);
    expect(fold.firstElementChild).not.toHaveAttribute("inert");
  });

  it("gives categories and 'All of' the same button, the current one outlined", () => {
    sheetTree("electronics:resistors");
    const all = screen.getByRole("link", { name: /^All of Electronics/ });
    const resistors = screen.getByRole("link", { name: /^Resistors/ });
    for (const el of [all, resistors]) expect(el.className).toMatch(/\bbg-tint\b/);
    expect(resistors.className).toMatch(/outline-chip-on/);
    expect(resistors.className).not.toMatch(/\bbg-chip-on\b/);
  });

  it("outlines the group's name button on the group's own page", () => {
    sheetTree("electronics:power");
    const name = document.querySelector("[data-tree-group='electronics:power']")!;
    expect(name).toHaveAttribute("aria-current", "page");
    expect(name.className).toMatch(/outline-chip-on/);
  });

  it("keeps a single-link group's two buttons, the funnel disabled", () => {
    sheetTree(null);
    const other = document.querySelector("[data-tree-group='electronics:other']")!;
    expect(other).toHaveAttribute("href", "/departments/electronics/accessories");
    const row = other.closest("li")!;
    const funnel = row.querySelector("button")!;
    expect(funnel).toBeDisabled();
    expect(funnel).toHaveAccessibleName("No subcategories in Accessories & Other");
    expect(funnel).not.toHaveAttribute("aria-expanded");
    expect(funnel).not.toHaveAttribute("aria-controls");
    expect(funnel.className).toMatch(/\bsize-11\b/);
    expect(funnel.className).toMatch(/\btext-ink-3\b/);
    expect(funnel.className).toMatch(/\bcursor-default\b/);
    expect(funnel.querySelector("svg[data-icon='funnel']")).not.toBeNull();
    // The same shape as a group that opens: name button, then a 6px gap.
    expect(funnel.parentElement!.className).toMatch(/\bgap-1\.5\b/);
    fireEvent.click(funnel);
    expect(document.querySelectorAll("[aria-expanded='true']")).toHaveLength(0);
  });

  it("leaves the desktop sidebar as it was", () => {
    tree("electronics:resistors");
    // The region the chevron names is the categories' own list, as before.
    for (const node of document.querySelectorAll("[data-tree-node]")) {
      const region = regionOf(node);
      expect(region.tagName).toBe("UL");
      expect(region).toHaveAttribute("role", "list");
      expect(region.parentElement).toBe(node);
    }
    expect(document.querySelector("button[data-funnel]")).toBeNull();
    expect(document.querySelector(".bg-tint")).toBeNull();
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
