import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PhotoFrame } from "@/components/photo-frame";

// No next/image mock any more: photos load straight from the supplier with a
// plain <img>, so there is no optimiser to stand in for.
// See docs/decisions/0003-supplier-images-load-direct.md.

const spinner = (container: HTMLElement) => container.querySelector('[class*="animate-spin"]');

describe("supplier photos", () => {
  it("shows the photo when there is one", () => {
    render(<PhotoFrame src="https://example.test/a.jpg" alt="LM358" />);
    expect(screen.getByAltText("LM358")).toBeInTheDocument();
  });

  it("falls back to a part glyph when the listing has no photo", () => {
    // 375 listings have none — a real state, not an edge case.
    const { container } = render(<PhotoFrame src={null} alt="LM358" />);
    expect(screen.queryByAltText("LM358")).not.toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("falls back when the supplier's URL stops resolving", () => {
    // Suppliers rotate their media; a stored URL rots. Same fallback, so a dead
    // link never renders as a broken-image icon.
    const { container } = render(<PhotoFrame src="https://example.test/gone.jpg" alt="LM358" />);
    fireEvent.error(screen.getByAltText("LM358"));
    expect(screen.queryByAltText("LM358")).not.toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("reserves the box so a list does not shift while images load", () => {
    const { container } = render(<PhotoFrame src={null} alt="x" />);
    expect(container.firstElementChild?.className).toContain("aspect-square");
  });

  describe("while the photo is still arriving", () => {
    // The page has to be usable before the photos are, because they now come
    // from the supplier at whatever pace the supplier manages.
    it("spins, then reports the photo once it loads", () => {
      const { container } = render(<PhotoFrame src="https://example.test/a.jpg" alt="a" />);

      expect(container.firstElementChild).toHaveAttribute("data-media", "loading");
      expect(spinner(container)).toBeInTheDocument();
      // Held in the DOM but transparent — the browser has to be decoding it for
      // `onLoad` to ever fire.
      expect(screen.getByAltText("a").className).toContain("opacity-0");

      fireEvent.load(screen.getByAltText("a"));

      expect(container.firstElementChild).toHaveAttribute("data-media", "photo");
      expect(spinner(container)).not.toBeInTheDocument();
      expect(screen.getByAltText("a").className).toContain("opacity-100");
    });

    it("reports the fallback state when there is nothing to wait for", () => {
      const { container } = render(<PhotoFrame src={null} alt="a" />);
      expect(container.firstElementChild).toHaveAttribute("data-media", "fallback");
      expect(spinner(container)).not.toBeInTheDocument();
    });

    it("goes back to loading when the same box is reused for another product", () => {
      // Load state is tracked per URL. Were it a bare boolean, a recycled row
      // would show the previous product's photo as already loaded.
      const { container, rerender } = render(
        <PhotoFrame src="https://example.test/a.jpg" alt="a" />,
      );
      fireEvent.load(screen.getByAltText("a"));
      expect(container.firstElementChild).toHaveAttribute("data-media", "photo");

      rerender(<PhotoFrame src="https://example.test/b.jpg" alt="b" />);
      expect(container.firstElementChild).toHaveAttribute("data-media", "loading");
      expect(spinner(container)).toBeInTheDocument();
    });

    it("keeps a failure attached to the URL that failed", () => {
      const { container, rerender } = render(
        <PhotoFrame src="https://example.test/gone.jpg" alt="a" />,
      );
      fireEvent.error(screen.getByAltText("a"));
      expect(container.firstElementChild).toHaveAttribute("data-media", "fallback");

      rerender(<PhotoFrame src="https://example.test/fine.jpg" alt="b" />);
      expect(container.firstElementChild).toHaveAttribute("data-media", "loading");
    });
  });

  describe("fetch pacing", () => {
    // Most of what keeps a 24-row page cheap now that photos are not optimised:
    // rows below the fold never request anything.
    it("lazy-loads by default", () => {
      render(<PhotoFrame src="https://example.test/a.jpg" alt="a" />);
      const img = screen.getByAltText("a");
      expect(img).toHaveAttribute("loading", "lazy");
      expect(img).toHaveAttribute("fetchpriority", "auto");
    });

    it("loads eagerly when it is the photo above the fold", () => {
      render(<PhotoFrame src="https://example.test/a.jpg" alt="a" priority />);
      const img = screen.getByAltText("a");
      expect(img).toHaveAttribute("loading", "eager");
      expect(img).toHaveAttribute("fetchpriority", "high");
    });

    it("sends no referrer, which also sidesteps naive hotlink checks", () => {
      render(<PhotoFrame src="https://example.test/a.jpg" alt="a" />);
      expect(screen.getByAltText("a")).toHaveAttribute("referrerpolicy", "no-referrer");
    });
  });
});
