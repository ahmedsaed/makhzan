/**
 * The footer: three labelled groups of links (the owner's choice over one
 * row), the theme toggle and "Made by Merope".
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SiteFooter } from "@/components/site-footer";

describe("the site footer", () => {
  it("groups its links under three headings", () => {
    render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");
    const groups = [
      [
        "makhzan",
        [
          ["About", "/about"],
          ["FAQ", "/faq"],
          ["Contact", "/contact"],
        ],
      ],
      [
        "For shops",
        [
          ["For suppliers", "/for-suppliers"],
          ["How we crawl", "/how-we-crawl"],
        ],
      ],
      [
        "Legal",
        [
          ["Privacy", "/privacy"],
          ["Terms", "/terms"],
        ],
      ],
    ] as const;
    expect(
      within(footer)
        .getAllByRole("heading")
        .map((h) => h.textContent),
    ).toEqual(groups.map(([title]) => title));
    for (const [title, links] of groups) {
      const nav = within(footer).getByRole("navigation", { name: title });
      expect(
        within(nav)
          .getAllByRole("link")
          .map((a) => [a.textContent, a.getAttribute("href")]),
      ).toEqual(links);
    }
  });

  it("keeps the home link, theme toggle and maker", () => {
    render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "makhzan, home" })).toHaveAttribute(
      "href",
      "/",
    );
    const theme = within(footer).getByRole("group", { name: "Theme" });
    expect(
      within(theme)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual(["Device", "Light", "Dark"]);
    expect(within(footer).getByRole("link", { name: "Merope" })).toHaveAttribute(
      "href",
      "https://merope.dev",
    );
  });

  it("makes every link 44 px tall (S4)", () => {
    render(<SiteFooter />);
    for (const nav of screen.getAllByRole("navigation")) {
      for (const link of within(nav).getAllByRole("link")) expect(link).toHaveClass("h-11");
    }
  });
});
