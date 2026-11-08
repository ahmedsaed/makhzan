import { describe, expect, it } from "vitest";

import { CLAMP_LINES, estimateLines } from "@/app/(site)/products/[id]/description";

describe("the description's line estimate", () => {
  it("wraps each paragraph on its own, and counts a blank line as one", () => {
    expect(estimateLines("short", 50)).toBe(1);
    expect(estimateLines("x".repeat(101), 50)).toBe(3);
    expect(estimateLines("a\n\nb", 50)).toBe(3);
  });

  it("clamps at 25 lines", () => {
    expect(CLAMP_LINES).toBe(25);
    expect(estimateLines(Array(26).fill("line").join("\n"), 100)).toBeGreaterThan(CLAMP_LINES);
    expect(estimateLines(Array(25).fill("line").join("\n"), 100)).toBe(CLAMP_LINES);
  });
});
