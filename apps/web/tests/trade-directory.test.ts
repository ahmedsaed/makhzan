import { describe, expect, it } from "vitest";

import { balancedColumns } from "@/app/(site)/trades/_components/browse-tile";
import type { Category } from "@/lib/api";
import { categoryLimit, tradeDirectory } from "@/lib/trade-directory";

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

/** One big trade with a two-level tree, one mid-sized flat one, one small. */
const CATEGORIES = [
  cat("seals-bearings", "seals", "Seals & Gaskets", null, 0),
  cat("seals-bearings", "seals-other", "Other Seals", "seals", 900),
  cat("seals-bearings", "o-rings", "O-Rings", "seals", 40000),
  cat("seals-bearings", "oil-seals", "Oil Seals", "seals", 250),
  ...Array.from({ length: 7 }, (_, i) =>
    cat("seals-bearings", `gasket-${i}`, `Gasket ${i}`, "seals", 10 + i),
  ),
  cat("seals-bearings", "transmission", "Bearings & Transmission", null, 0),
  cat("seals-bearings", "bearings", "Bearings", "transmission", 300),
  cat("seals-bearings", "filtration", "Filtration", null, 0),
  cat("seals-bearings", "air-filters", "Air Filters", "filtration", 0),
  ...Array.from({ length: 12 }, (_, i) => cat("piping", `valve-${i}`, `Valve ${i}`, null, 100 - i)),
  cat("timber", "oak", "Oak", null, 90),
  cat("timber", "teak", "Teak", null, 30),
  cat("timber", "other-wood", "Other Wood", null, 50),
  cat("timber", "pine", "Pine", null, 20),
  cat("timber", "ash", "Ash", null, 4),
  cat("timber", "elm", "Elm", null, 1),
];

describe("the trades directory", () => {
  const [seals, piping, timber] = tradeDirectory(CATEGORIES);

  it("lists trades largest first", () => {
    expect([seals.domain, piping.domain, timber.domain]).toEqual([
      "seals-bearings",
      "piping",
      "timber",
    ]);
  });

  it("maps a major trade group by group, leaving out empty groups", () => {
    expect(seals.major).toBe(true);
    expect(seals.groups.map((g) => [g.name, g.count])).toEqual([
      ["Seals & Gaskets", 41241],
      ["Bearings & Transmission", 300],
    ]);
    expect(seals.categories).toEqual([]);
    expect(seals.groups[0].href).toBe("/trades/seals-bearings/seals");
  });

  it("lists a group's biggest categories, the 'Other' bucket last, then counts the rest", () => {
    const [group] = seals.groups;
    expect(group.categories.map((c) => c.name)).toEqual([
      "O-Rings",
      "Oil Seals",
      "Gasket 6",
      "Gasket 5",
      "Gasket 4",
      "Gasket 3",
    ]);
    // 10 categories, 6 listed: "Other Seals" (900, but last by rule) is among the 4 more.
    expect(group.more).toBe(4);
  });

  it("gives a minor trade its biggest categories, more for a bigger trade", () => {
    expect(piping.major).toBe(false);
    expect(piping.categories).toHaveLength(categoryLimit(piping.count));
    expect(piping.more).toBe(12 - piping.categories.length);
    expect(timber.categories.map((c) => c.name)).toEqual(["Oak", "Teak", "Pine", "Ash"]);
    expect(timber.more).toBe(2);
    expect(timber.categoryCount).toBe(6);
  });

  it("scales the number of links with the trade's size", () => {
    expect(categoryLimit(50)).toBeLessThan(categoryLimit(500));
    expect(categoryLimit(500)).toBeLessThan(categoryLimit(5000));
  });

  it("makes a big minor trade wide, and only that", () => {
    const [, wide] = tradeDirectory([
      ...CATEGORIES,
      ...Array.from({ length: 30 }, (_, i) => cat("electrical", `c${i}`, `C${i}`, null, 40)),
    ]);
    expect(wide.domain).toBe("electrical");
    expect(wide.wide).toBe(true);
    expect(wide.categories).toHaveLength(10);
    expect(seals.wide).toBe(false);
    expect(timber.wide).toBe(false);
  });

  it("says what share of the catalogue each trade holds", () => {
    const total = seals.count + piping.count + timber.count;
    expect(seals.share).toBeCloseTo(seals.count / total);
  });
});

describe("tile rows on desktop", () => {
  it("balances rows instead of leaving one tile alone", () => {
    expect(balancedColumns(8, 5)).toBe(4);
    expect(balancedColumns(5, 5)).toBe(5);
    expect(balancedColumns(6, 4)).toBe(3);
    expect(balancedColumns(3, 4)).toBe(3);
    expect(balancedColumns(10, 6)).toBe(5);
    expect(balancedColumns(0, 4)).toBe(1);
  });
});
