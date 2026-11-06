import { describe, expect, it } from "vitest";

import { formatPrice } from "@/lib/format";

describe("prices", () => {
  it("keeps a fractional price exact — a resistor is 3.50, not 4", () => {
    expect(formatPrice(3.5, "EGP", "en")).toMatch(/3\.50/);
  });

  it("does not invent decimals on a whole price", () => {
    expect(formatPrice(350, "EGP", "en")).not.toMatch(/350\.00/);
  });

  it("formats in Arabic without throwing", () => {
    expect(formatPrice(185, "EGP", "ar")).toBeTruthy();
  });

  it("survives a currency Intl does not know", () => {
    // Supplier data is not guaranteed to be a valid ISO code.
    expect(formatPrice(10, "ZZZ", "en")).toContain("10");
  });
});
