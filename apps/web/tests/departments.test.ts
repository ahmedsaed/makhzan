import { describe, expect, it } from "vitest";

import type { Category } from "@/lib/api";
import { asPhrase, insideOf, totalOf, departmentSummaries, departmentTree } from "@/lib/departments";

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

const SEALS = [
  cat("seals-bearings", "seals", "Seals & Gaskets", null, 0),
  cat("seals-bearings", "o-rings", "O-Rings", "seals", 400),
  cat("seals-bearings", "oil-seals", "Oil Seals", "seals", 250),
  cat("seals-bearings", "seals-other", "Other Seals", "seals", 500),
  cat("seals-bearings", "transmission", "Bearings & Transmission", null, 0),
  cat("seals-bearings", "bearings", "Bearings", "transmission", 300),
  cat("seals-bearings", "couplings", "Couplings", "transmission", 40),
  cat("seals-bearings", "filtration", "Filtration", null, 0),
  cat("seals-bearings", "air-filters", "Air Filters", "filtration", 0),
];
const FLAT = [cat("timber", "oak", "Oak", null, 90), cat("timber", "teak", "Teak", null, 30)];

describe("what's inside a department", () => {
  it("is its biggest leaf categories, largest first", () => {
    expect(insideOf("seals-bearings", SEALS, 3)).toEqual(["O-Rings", "Bearings", "Oil Seals"]);
  });

  it("never names an 'Other' bucket, however big", () => {
    expect(insideOf("seals-bearings", SEALS)).not.toContain("Other Seals");
  });

  it("only looks inside the department asked about", () => {
    expect(insideOf("timber", [...SEALS, ...FLAT])).toEqual(["Oak", "Teak"]);
  });

  it("reads as one phrase without lowering acronyms or part names", () => {
    expect(asPhrase(["Resistors", "Integrated Circuits", "PLCs", "O-Rings", "3D Printers"])).toBe(
      "Resistors, integrated circuits, PLCs, O-Rings, 3D printers",
    );
  });

  it("lowers the first name's later words too, so the phrase reads in one style", () => {
    expect(asPhrase(["Batteries & Chargers", "Power Supplies", "LED Strips"])).toBe(
      "Batteries & chargers, power supplies, LED strips",
    );
  });
});

describe("departments are listed by size", () => {
  it("orders departments largest first and drops empty ones", () => {
    const departments = departmentSummaries([...FLAT, ...SEALS, cat("garden", "mowers", "Mowers", null, 0)]);
    expect(departments.map((t) => [t.domain, t.count])).toEqual([
      ["seals-bearings", 1490],
      ["timber", 120],
    ]);
    expect(departments[0].inside[0]).toBe("O-Rings");
  });
});

describe("a department's tree", () => {
  it("totals a group over its children", () => {
    expect(totalOf("seals-bearings:seals", SEALS)).toBe(1150);
    expect(totalOf("seals-bearings:bearings", SEALS)).toBe(300);
  });

  it("lists groups by size and leaves out empty ones", () => {
    const { groups, group, children, top } = departmentTree(SEALS);
    expect(groups.map((g) => g.slug)).toEqual(["seals", "transmission"]);
    expect(group).toBeNull();
    expect(children).toEqual([]);
    // Nothing selected: the department's biggest categories stand in.
    expect(top.map((c) => c.slug)).toEqual([
      "seals-other",
      "o-rings",
      "bearings",
      "oil-seals",
      "couplings",
    ]);
  });

  it("selects a leaf's group and lists that group's categories", () => {
    const { group, children } = departmentTree(SEALS, "seals-bearings:bearings");
    expect(group?.slug).toBe("transmission");
    expect(children.map((c) => c.slug)).toEqual(["bearings", "couplings"]);
  });

  it("selects a group by itself", () => {
    expect(departmentTree(SEALS, "seals-bearings:seals").group?.slug).toBe("seals");
  });

  it("adds no biggest-categories row to a flat department", () => {
    const { groups, top } = departmentTree(FLAT);
    expect(groups.map((g) => g.slug)).toEqual(["oak", "teak"]);
    expect(top).toEqual([]);
  });
});
