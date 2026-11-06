import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Freshness, StaleNote } from "@/components/freshness";
import { daysSince, freshnessTier, parseVerified } from "@/lib/freshness";

const NOW = new Date("2026-11-06T12:00:00Z");
const daysAgo = (days: number) => new Date(NOW.getTime() - days * 86_400_000);

describe("freshness tiers (rule F2)", () => {
  it.each([
    [0, "quiet"],
    [14, "quiet"],
    [15, "muted"],
    [45, "muted"],
    [46, "warn"],
    [400, "warn"],
  ] as const)("%i days old is %s", (days, tier) => {
    expect(freshnessTier(daysAgo(days), NOW)).toBe(tier);
  });

  it("counts whole days, so 14 days and 23 hours is still 14", () => {
    const almost = new Date(daysAgo(15).getTime() + 3_600_000);
    expect(daysSince(almost, NOW)).toBe(14);
    expect(freshnessTier(almost, NOW)).toBe("quiet");
  });

  it("never goes negative when the clocks disagree", () => {
    expect(daysSince(new Date(NOW.getTime() + 60_000), NOW)).toBe(0);
  });
});

describe("check times arrive in two shapes", () => {
  it("reads the index's epoch seconds and the API's ISO strings alike", () => {
    expect(parseVerified(1_760_000_000)).toEqual(new Date(1_760_000_000_000));
    expect(parseVerified("2026-09-01T10:00:00Z")?.toISOString()).toBe("2026-09-01T10:00:00.000Z");
  });

  it("gives null for nothing, or for nonsense", () => {
    expect(parseVerified(null)).toBeNull();
    expect(parseVerified("not a date")).toBeNull();
  });
});

describe("Freshness", () => {
  it("is quiet and relative when recent (F1)", () => {
    render(<Freshness lastVerified={daysAgo(12)} now={NOW} />);
    const label = screen.getByText("checked 12 days ago");
    expect(label).toHaveAttribute("data-freshness", "quiet");
    expect(label.className).toContain("text-ink-2");
  });

  it("is muted from 15 days", () => {
    render(<Freshness lastVerified={daysAgo(29)} now={NOW} />);
    expect(screen.getByText("checked 29 days ago").className).toContain("text-age-muted");
  });

  it("warns past 45 days, in the warn colours and never the action colour", () => {
    render(<Freshness lastVerified={daysAgo(74)} now={NOW} />);
    const label = screen.getByText("Price may be out of date (74 days)");
    expect(label.className).toContain("text-warn-ink");
    expect(label.className).not.toMatch(/action/);
  });

  it("says today rather than 0 days ago", () => {
    render(<Freshness lastVerified={daysAgo(0)} now={NOW} />);
    expect(screen.getByText("checked today")).toBeInTheDocument();
  });
});

describe("StaleNote", () => {
  it("tells you what to do about an old price", () => {
    render(<StaleNote lastVerified={daysAgo(74)} now={NOW} />);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Price may be out of date. Last checked 74 days ago. Confirm it on the shop's page.",
    );
  });

  it("renders nothing for a price that is not stale", () => {
    const { container } = render(<StaleNote lastVerified={daysAgo(45)} now={NOW} />);
    expect(container).toBeEmptyDOMElement();
  });
});
