import "@testing-library/jest-dom/vitest";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ResultList } from "@/components/result-list";
import type { SearchHit } from "@/lib/api";
import { PAGE_SIZE } from "@/lib/results-query";
import { writeView } from "@/lib/view-preference";

/**
 * A full page of results ends on a complete row at every width: the page size
 * is divisible by every column count the grid uses. The column counts are read
 * off the class names the list actually renders (the same Tailwind classes that
 * lay it out), so changing one without the other fails here.
 */

const hit = (index: number): SearchHit => ({
  id: `p-${index}`,
  domain: "electronics",
  part_number: null,
  title_en: `Part ${index}`,
  title_ar: null,
  brand: null,
  category_slug: "ics",
  category_ref: "electronics:ics",
  category_name: "ICs",
  supplier_name: "Shop A",
  supplier_count: 1,
  offer_count: 1,
  min_price: 10,
  max_price: 10,
  currency: "EGP",
  in_stock: true,
  image: null,
  last_verified_at: Date.now() / 1000,
});

const page = Array.from({ length: PAGE_SIZE }, (_, index) => hit(index));

/** Tailwind's breakpoints, smallest first; "" is the base (phones). */
const BREAKPOINTS = ["", "sm", "md", "lg", "xl", "2xl"] as const;

/** The number of columns in force at each breakpoint, from `grid-cols-N` classes. */
function columnsByBreakpoint(className: string): Record<string, number> {
  const declared = new Map<string, number>();
  for (const token of className.split(/\s+/)) {
    const match = /^(?:([a-z0-9]+):)?grid-cols-(\d+)$/.exec(token);
    if (match) declared.set(match[1] ?? "", Number(match[2]));
  }
  // Mobile first: a breakpoint without its own class inherits the one below.
  const out: Record<string, number> = {};
  let current = 1;
  for (const breakpoint of BREAKPOINTS) {
    current = declared.get(breakpoint) ?? current;
    out[breakpoint || "base"] = current;
  }
  return out;
}

afterEach(() => {
  act(() => writeView("list"));
  window.localStorage.clear();
});

describe("a full page fills its last row", () => {
  it("the page size is divisible by the grid's columns at every breakpoint", () => {
    act(() => writeView("grid"));
    const { container } = render(<ResultList hits={page} />);
    const list = container.querySelector("[data-view=grid]")!;
    expect(list).not.toBeNull();
    const columns = columnsByBreakpoint(list.className);
    // The grid really declares more than one width, or this proves nothing.
    expect(new Set(Object.values(columns)).size).toBeGreaterThan(1);
    for (const [breakpoint, count] of Object.entries(columns)) {
      expect(PAGE_SIZE % count, `${PAGE_SIZE} results in ${count} columns at ${breakpoint}`).toBe(
        0,
      );
    }
  });

  it("the list is one result per row at every breakpoint", () => {
    const { container } = render(<ResultList hits={page} />);
    const list = container.querySelector("[data-view=list]")!;
    expect(list).not.toBeNull();
    expect(list.className).not.toMatch(/grid-cols-/);
    expect(list.querySelectorAll("[data-result=row]")).toHaveLength(PAGE_SIZE);
  });
});
