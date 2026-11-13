/**
 * The /how-we-crawl copy, read as prose: each fact once, the questions as
 * pointers, and no claim the page cannot yet stand behind.
 */
import { describe, expect, it } from "vitest";

import { CONTENTS, crawlingContent, SECTION } from "@/lib/content/crawling";

/** Every prose string in the copy, leaving out the text to copy as it is. */
function prose(value: unknown, key = ""): string[] {
  if (["snippet", "request", "block"].includes(key)) return [];
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap((item) => prose(item));
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([k, v]) => prose(v, k));
  }
  return [];
}

describe("the how-we-crawl copy", () => {
  it("states each sentence once", () => {
    const sentences = prose(crawlingContent)
      .flatMap((text) => text.split(/(?<=[.!?:])\s+/))
      .map((s) => s.trim().toLowerCase())
      .filter((s) => s.length > 25);
    const seen = new Set<string>();
    const repeated = sentences.filter((s) => (seen.has(s) ? true : (seen.add(s), false)));
    expect(repeated).toEqual([]);
  });

  it("answers each question briefly and points to the section that says it in full", () => {
    const ids = new Set<string>([...Object.values(SECTION), "top"]);
    for (const item of crawlingContent.faq.items) {
      expect(item.answer.length, item.question).toBeLessThanOrEqual(50);
      expect(ids.has(item.more.href.slice(1)), item.more.href).toBe(true);
    }
  });

  it("does not mention Cloudflare until the registration is settled", () => {
    expect(JSON.stringify(crawlingContent)).not.toMatch(/cloudflare/i);
  });

  it("lists every section in the contents, in order", () => {
    expect(CONTENTS.map((c) => c.href.slice(1))).toEqual([
      SECTION.read,
      SECTION.verify,
      SECTION.robots,
      SECTION.pace,
      SECTION.keep,
      SECTION.activity,
      SECTION.suppliers,
      SECTION.faq,
      SECTION.contact,
    ]);
  });
});
