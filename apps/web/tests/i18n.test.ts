import { describe, expect, it } from "vitest";

import {
  DEFAULT_LANG,
  LANGS,
  dirOf,
  getDictionary,
  isLang,
  localeOf,
  preferredLang,
} from "@/lib/i18n";

describe("language as a route, not state", () => {
  it("only accepts the two languages that have URLs", () => {
    expect(isLang("en")).toBe(true);
    expect(isLang("ar")).toBe(true);
    expect(isLang("fr")).toBe(false);
    expect(isLang(undefined)).toBe(false);
  });

  it("drives direction from the language alone", () => {
    expect(dirOf("ar")).toBe("rtl");
    expect(dirOf("en")).toBe("ltr");
  });

  it("formats for Egypt, not for the language in general", () => {
    expect(localeOf("ar")).toBe("ar-EG");
    expect(localeOf("en")).toBe("en-EG");
  });
});

describe("Accept-Language negotiation", () => {
  it.each([
    ["ar-EG,ar;q=0.9,en;q=0.8", "ar"],
    ["en-GB,en;q=0.9", "en"],
    ["fr-FR,fr;q=0.9,ar;q=0.5", "ar"],
  ])("picks %s → %s", (header, expected) => {
    expect(preferredLang(header)).toBe(expected);
  });

  it("falls back when the header is missing or unhelpful", () => {
    expect(preferredLang(null)).toBe(DEFAULT_LANG);
    expect(preferredLang("")).toBe(DEFAULT_LANG);
    expect(preferredLang("de,zh")).toBe(DEFAULT_LANG);
  });
});

describe("dictionaries", () => {
  it("define exactly the same keys in both languages", () => {
    const [en, ar] = LANGS.map((lang) => Object.keys(getDictionary(lang)).sort());
    expect(ar).toEqual(en);
  });

  it("leaves nothing untranslated", () => {
    const en = getDictionary("en");
    const ar = getDictionary("ar");
    const untranslated = Object.keys(en).filter(
      (key) => en[key as keyof typeof en] === ar[key as keyof typeof ar],
    );
    expect(untranslated).toEqual([]);
  });
});
