/**
 * The site's own pages: /about, /faq, /contact and /terms (lib/content), and
 * the links to /contact from /privacy and /how-we-crawl.
 */
import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Category, Stats } from "@/lib/api";
import { aboutLead, aboutSections, CATALOGUE_FALLBACK, catalogueLine } from "@/lib/content/about";
import { contactRoutes, HELLO_EMAIL } from "@/lib/content/contact";
import { CONTACT_EMAIL } from "@/lib/content/crawling";
import { faqGroups, faqJsonLd } from "@/lib/content/faq";
import { privacySections } from "@/lib/content/privacy";
import { hrefsOf, plainText, type Rich } from "@/lib/content/prose";
import { TERMS_UPDATED, termsLead, termsSections } from "@/lib/content/terms";
import { STALE_AFTER_DAYS } from "@/lib/freshness";
import { EMAIL_KEPT_DAYS, REASONS } from "@/lib/report";
import { routes } from "@/lib/routes";

const api = vi.hoisted(() => ({
  fetchCategories: vi.fn<() => Promise<Category[]>>(),
  fetchStats: vi.fn<() => Promise<Stats>>(),
}));

vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  ...api,
}));

const cat = (domain: string, slug: string, count: number): Category => ({
  ref: `${domain}:${slug}`,
  domain,
  slug,
  name_en: slug,
  name_ar: null,
  parent: null,
  count,
});

/** Every rich paragraph of the four pages' copy. */
const ALL_RICH: Rich[] = [
  [aboutLead],
  ...aboutSections.flatMap((s) => [...(s.before ?? []), ...(s.after ?? [])]),
  ...faqGroups.flatMap((g) => g.items.flatMap((item) => item.answer)),
  ...contactRoutes.map((r) => r.body),
  termsLead,
  ...termsSections.flatMap((s) => s.blocks.flatMap((b) => (b.kind === "p" ? [b.text] : b.items))),
];
const COPY = JSON.stringify([aboutSections, faqGroups, contactRoutes, termsLead, termsSections]);
const FAQ_TEXT = faqGroups
  .flatMap((g) => g.items.flatMap((item) => [item.question, ...item.answer.map(plainText)]))
  .join("\n");
const ABOUT_TEXT = JSON.stringify(aboutSections);

/** The site's pages a reading page may link to. */
const OUR_PAGES = new Set([
  routes.home(),
  routes.howWeCrawl(),
  routes.forSuppliers(),
  routes.privacy(),
  routes.about(),
  routes.faq(),
  routes.contact(),
  routes.terms(),
]);

describe("catalogueLine", () => {
  it("states the live totals, formatted like the rest of the site", () => {
    expect(catalogueLine({ products: 57207, suppliers: 8, categories: 249 }, 16)).toBe(
      "Today: 57,207 products from 8 shops in 16 departments.",
    );
  });

  it("speaks of one shop and one department in the singular", () => {
    expect(catalogueLine({ products: 1, suppliers: 1, categories: 1 }, 1)).toBe(
      "Today: 1 product from 1 shop in 1 department.",
    );
  });

  it("leaves out a department count it could not get", () => {
    expect(catalogueLine({ products: 1200, suppliers: 3, categories: 9 }, null)).toBe(
      "Today: 1,200 products from 3 shops.",
    );
    expect(catalogueLine({ products: 1200, suppliers: 3, categories: 9 }, 0)).toBe(
      "Today: 1,200 products from 3 shops.",
    );
  });

  it("falls back to words without totals, and never says zero", () => {
    expect(catalogueLine(null, 16)).toBe(CATALOGUE_FALLBACK);
    expect(catalogueLine({ products: 0, suppliers: 8, categories: 0 }, 16)).toBe(
      CATALOGUE_FALLBACK,
    );
    expect(catalogueLine({ products: 900, suppliers: 0, categories: 0 }, 16)).toBe(
      CATALOGUE_FALLBACK,
    );
    expect(CATALOGUE_FALLBACK).toBe("It lists products from shops across Egypt.");
  });
});

describe("the about page", () => {
  async function renderAbout() {
    const { default: AboutPage } = await import("@/app/(site)/about/page");
    render(await AboutPage());
  }
  const size = () => document.querySelector("[data-catalogue-size]");

  beforeEach(() => {
    api.fetchStats.mockReset();
    api.fetchCategories.mockReset();
  });

  it("shows the live counts, departments from the categories that hold products", async () => {
    api.fetchStats.mockResolvedValue({ products: 57207, suppliers: 8, categories: 249 });
    api.fetchCategories.mockResolvedValue([
      cat("electronics", "ics", 100),
      cat("electronics", "resistors", 20),
      cat("tools", "calipers", 5),
      cat("garden", "nothing", 0),
    ]);
    await renderAbout();
    expect(size()).toHaveTextContent("Today: 57,207 products from 8 shops in 2 departments.");
    expect(screen.getByRole("heading", { level: 1, name: "About makhzan" })).toBeVisible();
  });

  it("still renders, in words, when the API is down", async () => {
    api.fetchStats.mockRejectedValue(new Error("down"));
    api.fetchCategories.mockRejectedValue(new Error("down"));
    await renderAbout();
    expect(size()).toHaveTextContent(CATALOGUE_FALLBACK);
    expect(size()!.textContent).not.toMatch(/\d/);
    expect(screen.getByRole("heading", { name: "Who pays" })).toBeVisible();
  });

  it("never shows a zero from an empty index", async () => {
    api.fetchStats.mockResolvedValue({ products: 0, suppliers: 0, categories: 0 });
    api.fetchCategories.mockResolvedValue([]);
    await renderAbout();
    expect(size()).toHaveTextContent(CATALOGUE_FALLBACK);
  });

  it("keeps the claims the owner approved", async () => {
    expect(ABOUT_TEXT).toContain("never by payment");
    expect(ABOUT_TEXT).toContain("Most products are sold by one listed shop.");
    expect(ABOUT_TEXT).toContain("no shop pays to be listed or to rank higher");
  });

  it("links how we crawl, contact, for suppliers and the general address", async () => {
    api.fetchStats.mockResolvedValue({ products: 10, suppliers: 2, categories: 1 });
    api.fetchCategories.mockResolvedValue([]);
    await renderAbout();
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(
      expect.arrayContaining([
        "/how-we-crawl",
        "/contact",
        "/for-suppliers",
        `mailto:${HELLO_EMAIL}`,
        "https://merope.dev",
      ]),
    );
  });
});

describe("the FAQ", () => {
  const items = faqGroups.flatMap((g) => g.items);

  it("gives every question a unique, linkable id", () => {
    const ids = items.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[a-z][a-z-]*[a-z]$/);
  });

  it("renders each question as <details> with its id, closed until opened", async () => {
    const { default: FaqPage } = await import("@/app/(site)/faq/page");
    const { container } = render(<FaqPage />);
    const details = container.querySelectorAll("details");
    expect(details).toHaveLength(items.length);
    for (const [i, item] of items.entries()) {
      expect(details[i].id).toBe(item.id);
      expect(details[i].open).toBe(false);
      expect(details[i].querySelector("summary")).toHaveTextContent(item.question);
    }
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(
      faqGroups.map((g) => g.title),
    );
  });

  it("names each group's section by its visible heading, not a copy of it", async () => {
    const { default: FaqPage } = await import("@/app/(site)/faq/page");
    const { container } = render(<FaqPage />);
    const sections = [...container.querySelectorAll("section")];
    expect(sections).toHaveLength(faqGroups.length);
    for (const [i, section] of sections.entries()) {
      expect(section).not.toHaveAttribute("aria-label");
      const heading = section.querySelector("h2")!;
      expect(heading.id).not.toBe("");
      expect(section).toHaveAttribute("aria-labelledby", heading.id);
      expect(screen.getByRole("region", { name: faqGroups[i].title })).toBe(section);
    }
  });

  it("carries FAQPage structured data with every question and its plain answer", async () => {
    const { default: FaqPage } = await import("@/app/(site)/faq/page");
    const { container } = render(<FaqPage />);
    const script = container.querySelector('script[type="application/ld+json"]')!;
    const data = JSON.parse(script.innerHTML);
    expect(data["@type"]).toBe("FAQPage");
    expect(data.mainEntity).toHaveLength(items.length);
    expect(data.mainEntity[1]).toMatchObject({
      "@type": "Question",
      name: "Why is the price different on the shop’s site?",
    });
    expect(data.mainEntity[1].acceptedAnswer.text).toContain("tell us with Report a problem");
    expect(faqJsonLd(faqGroups, "https://x.test/faq").url).toBe("https://x.test/faq");
  });

  it("says what the code does", () => {
    expect(FAQ_TEXT).toContain(`not checked in over ${STALE_AFTER_DAYS} days`);
    expect(FAQ_TEXT).toContain(`deleted after ${EMAIL_KEPT_DAYS} days`);
    expect(FAQ_TEXT).toContain("Removal takes at most 7 days");
    // The report form's own words, not a paraphrase.
    for (const key of ["same_as_other", "offers_not_same"]) {
      expect(FAQ_TEXT).toContain(`“${REASONS.find((r) => r.key === key)!.title}”`);
    }
  });

  it("keeps the owner's decisions", () => {
    // Dropped: not every small shop is read more often.
    expect(FAQ_TEXT).not.toMatch(/small shops are read more often/i);
    // A buyer may suggest a shop by email.
    const missing = items.find((item) => item.id === "missing-shop")!;
    expect(hrefsOf(missing.answer.flat())).toContain(`mailto:${HELLO_EMAIL}`);
    // Data reuse is refused.
    const reuse = plainText(items.find((item) => item.id === "use-data")!.answer.flat());
    expect(reuse).toContain("makhzan offers no API or data licence");
    expect(reuse).toContain(HELLO_EMAIL);
  });

  it("draws the report button as an illustration, not a button", async () => {
    const { default: FaqPage } = await import("@/app/(site)/faq/page");
    const { container } = render(<FaqPage />);
    const flag = container.querySelector("[data-flag-illustration]")!;
    expect(flag).toHaveTextContent("Report a problem");
    expect(flag.tagName).toBe("SPAN");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("the contact page", () => {
  it("routes each need to the right place", async () => {
    const { default: ContactPage } = await import("@/app/(site)/contact/page");
    const { container } = render(<ContactPage />);
    const card = (id: string) =>
      container.querySelector<HTMLElement>(`[data-contact-route="${id}"]`)!;

    expect(card("wrong").querySelector("[data-flag-illustration]")).not.toBeNull();
    expect(within(card("wrong")).queryByRole("link")).toBeNull();
    expect(within(card("shops")).getByRole("link", { name: "For suppliers" })).toHaveAttribute(
      "href",
      "/for-suppliers",
    );
    expect(
      within(card("data")).getByRole("link", { name: `Email ${CONTACT_EMAIL}` }),
    ).toHaveAttribute("href", `mailto:${CONTACT_EMAIL}`);
    expect(within(card("data")).getByRole("link", { name: "Privacy" })).toHaveAttribute(
      "href",
      "/privacy",
    );
    expect(
      within(card("else")).getByRole("link", { name: `Email ${HELLO_EMAIL}` }),
    ).toHaveAttribute("href", `mailto:${HELLO_EMAIL}`);
    expect(screen.getByRole("link", { name: "FAQ" })).toHaveAttribute("href", "/faq");
    expect(container.querySelector("form")).toBeNull();
  });
});

describe("the terms", () => {
  it("say when they were last updated", async () => {
    const { default: TermsPage } = await import("@/app/(site)/terms/page");
    render(<TermsPage />);
    expect(TERMS_UPDATED).toBe("13 November 2026");
    expect(screen.getByText(`Last updated ${TERMS_UPDATED}`)).toBeVisible();
    expect(screen.getByRole("heading", { level: 1, name: "Terms of use" })).toBeVisible();
    expect(screen.getByRole("link", { name: "robots.txt" })).toHaveAttribute("href", "/robots.txt");
  });
});

describe("all four pages", () => {
  it("name no address but makhzan's two", () => {
    const addresses = new Set(COPY.match(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g));
    expect(addresses).toEqual(new Set([CONTACT_EMAIL, HELLO_EMAIL]));
    expect(HELLO_EMAIL).toBe("hello@merope.dev");
  });

  it("link only to our own pages, our two addresses, Merope and robots.txt", () => {
    const allowed = new Set([
      ...OUR_PAGES,
      `mailto:${CONTACT_EMAIL}`,
      `mailto:${HELLO_EMAIL}`,
      "https://merope.dev",
      "/robots.txt",
    ]);
    const hrefs = ALL_RICH.flatMap(hrefsOf);
    expect(hrefs.length).toBeGreaterThan(10);
    for (const href of hrefs) expect(allowed, href).toContain(href);
  });

  it("carry nothing from the mockup", () => {
    expect(COPY).not.toMatch(/mockup|lawyer|\blive\b|set on publish/i);
  });
});

describe("links to /contact", () => {
  it("from /privacy", () => {
    const who = privacySections.find((s) => s.id === "who")!;
    const rich = who.blocks.flatMap((b) => (b.kind === "rich" ? [b.parts] : []));
    expect(rich.flatMap(hrefsOf)).toContain("/contact");
  });

  it("from /how-we-crawl, without naming Cloudflare", () => {
    const page = readFileSync(join(__dirname, "..", "app/(site)/how-we-crawl/page.tsx"), "utf8");
    expect(page).toContain("href={routes.contact()}");
    expect(page).not.toMatch(/cloudflare/i);
  });
});
