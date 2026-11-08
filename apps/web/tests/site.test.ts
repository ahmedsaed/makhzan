import { afterEach, describe, expect, it, vi } from "vitest";

import { absoluteUrl, siteUrl } from "@/lib/site";

describe("siteUrl", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("is the configured public origin", () => {
    vi.stubEnv("SITE_URL", "https://makhzan.example");
    expect(siteUrl().origin).toBe("https://makhzan.example");
    expect(absoluteUrl("/products/abc")).toBe("https://makhzan.example/products/abc");
  });

  it("falls back to the dev server when unset or malformed", () => {
    vi.stubEnv("SITE_URL", "");
    expect(absoluteUrl("/departments")).toBe("http://localhost:3000/departments");
    vi.stubEnv("SITE_URL", "not a url");
    expect(absoluteUrl("/departments")).toBe("http://localhost:3000/departments");
  });
});
