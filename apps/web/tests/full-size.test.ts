import { describe, expect, it } from "vitest";

import { fullSizeCandidates } from "@/lib/full-size";

const THUMB =
  "https://shop-a.test/uploads/cache/2025-03-14/product/image/abc123def-q-80-h-150.webp";

describe("full-size candidates for a cached thumbnail", () => {
  it("drops the cache segment and resize suffix, trying .jpeg then .png", () => {
    expect(fullSizeCandidates(THUMB)).toEqual([
      "https://shop-a.test/uploads/2025-03-14/product/image/abc123def.jpeg",
      "https://shop-a.test/uploads/2025-03-14/product/image/abc123def.png",
    ]);
  });

  it("keeps a stem that has dashes of its own, and ignores a query string", () => {
    expect(
      fullSizeCandidates(
        "https://shop-a.test/uploads/cache/2024/product/image/servo-sg-90-q-80-h-150.webp?v=2",
      )[0],
    ).toBe("https://shop-a.test/uploads/2024/product/image/servo-sg-90.jpeg");
  });

  it("accepts a width as well as a height", () => {
    expect(
      fullSizeCandidates(
        "https://shop-a.test/uploads/cache/d/product/image/x-q-75-w-300-h-300.webp",
      ),
    ).toEqual([
      "https://shop-a.test/uploads/d/product/image/x.jpeg",
      "https://shop-a.test/uploads/d/product/image/x.png",
    ]);
  });

  it("leaves every other photo alone", () => {
    for (const src of [
      "https://shop-b.test/img/caliper-1.jpg",
      "https://shop-b.test/uploads/2025/product/image/abc.jpeg",
      "https://shop-b.test/uploads/cache/2025/product/image/abc.webp",
      "https://shop-b.test/cdn/shop/files/abc-q-80-h-150.webp",
      "",
    ]) {
      expect(fullSizeCandidates(src), src).toEqual([]);
    }
  });
});
