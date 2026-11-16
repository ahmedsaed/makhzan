/**
 * The shop view's pieces and the AI badge in jsdom: picking by "View listing"
 * and by a tab, what follows (title, ring, tab, button), the URL, the badge's
 * popover by pointer and keyboard, and the AI note opening Report a problem.
 * The browser-level checks are in tests/e2e/shop-view.spec.ts.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AiNote,
  OfferRowShell,
  type PickMeta,
  PickerRadio,
  ShopTitle,
  ShopViewProvider,
  ShopViewStatus,
  ViewListing,
  WhenAction,
} from "@/app/(site)/products/[id]/shop-view";
import { AiBadge, AiPill } from "@/components/ai-badge";
import { ReportProblem } from "@/components/report-problem";
import type { ReportContext } from "@/lib/report";
import { AI_EXPLAINED, AI_LABEL } from "@/lib/shop-view";

// `?shop=` as Next's router reports it (useSearchParams), set per test.
const nav = vi.hoisted(() => ({ shop: null as string | null }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(nav.shop ? { shop: nav.shop } : {}),
}));

const META: Record<string, PickMeta> = {
  "o-nile": {
    slug: "nile-parts",
    shop: "Nile Parts",
    title: "TB6600 Driver 4A, Nile's title",
    linkable: true,
    photo: 0,
    detail: 1,
  },
  "o-volt": {
    slug: "volt-corner",
    shop: "Volt Corner",
    title: "TB6600 Module for NEMA 17, Volt's title",
    linkable: true,
    photo: 2,
    detail: 0,
  },
  "o-delta": {
    slug: "delta-bench",
    shop: "Delta Bench",
    title: "TB6600 Controller, Delta's title",
    linkable: false,
    photo: null,
    detail: null,
  },
};

const LEADS = { "nile-parts": "o-nile", "volt-corner": "o-volt", "delta-bench": "o-delta" };

function Page({ initial = "o-nile", explicit = false }: { initial?: string; explicit?: boolean }) {
  return (
    <ShopViewProvider
      initial={initial}
      explicit={explicit}
      primary="o-nile"
      meta={META}
      leads={LEADS}
    >
      <ShopTitle fallback="TB6600 Stepper Motor Driver" />
      <ul>
        {Object.entries(META).map(([id, meta]) => (
          <OfferRowShell key={id} offer={id}>
            {meta.shop}
            <ViewListing offer={id} slug={meta.slug!} shop={meta.shop} />
          </OfferRowShell>
        ))}
      </ul>
      <div role="radiogroup" aria-label="What the shops say">
        {["o-volt", "o-nile"].map((id, index) => (
          <label key={id}>
            <PickerRadio index={index} offer={id} />
            {META[id].shop}
          </label>
        ))}
      </div>
      {["o-nile", "o-volt", "o-delta"].map((id) => (
        <WhenAction key={id} offer={id}>
          <a href={`https://${META[id].slug}.test`}>View at {META[id].shop}</a>
        </WhenAction>
      ))}
      <ShopViewStatus />
    </ShopViewProvider>
  );
}

let replace: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  nav.shop = null;
  window.history.pushState(null, "", "/products/p-ai");
  replace = vi.spyOn(window.history, "replaceState");
});
afterEach(() => vi.restoreAllMocks());

const row = (shop: string) => screen.getByText(shop, { selector: "li > *, li" }).closest("li")!;

describe("the shop view", () => {
  it("opens on the cheapest offer: its title, ring, tab and button", () => {
    render(<Page />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Nile's title");
    expect(row("Nile Parts")).toHaveAttribute("aria-current", "true");
    expect(within(row("Nile Parts")).getByText("Showing this listing")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Nile Parts" })).toBeChecked();
    expect(screen.getByRole("link", { name: "View at Nile Parts" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View at Volt Corner" })).toBeNull();
    // Nothing is announced, and the URL is left alone, until someone picks.
    expect(screen.getByRole("status")).toHaveTextContent("");
    expect(replace).not.toHaveBeenCalled();
  });

  it("“View listing” picks a shop: everything follows, and the URL says so", () => {
    render(<Page />);
    const link = screen.getByRole("link", { name: "View Volt Corner’s listing on this page" });
    expect(link).toHaveAttribute("href", "?shop=volt-corner");
    fireEvent.click(link);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Volt's title");
    expect(row("Volt Corner")).toHaveAttribute("aria-current", "true");
    expect(row("Volt Corner")).toHaveAttribute("data-picked");
    expect(row("Nile Parts")).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("radio", { name: "Volt Corner" })).toBeChecked();
    expect(screen.getByRole("link", { name: "View at Volt Corner" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View at Nile Parts" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Showing Volt Corner’s listing");
    // Replaced, never pushed: no history entry per pick.
    expect(replace).toHaveBeenCalledWith(null, "", "/products/p-ai?shop=volt-corner");
  });

  it("a tab picks its shop", () => {
    render(<Page />);
    fireEvent.click(screen.getByRole("radio", { name: "Volt Corner" }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Volt's title");
    expect(row("Volt Corner")).toHaveAttribute("aria-current", "true");
  });

  it("a shop with no tab and no link out keeps the open tab and the cheapest's button", () => {
    render(<Page />);
    fireEvent.click(screen.getByRole("link", { name: "View Delta Bench’s listing on this page" }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Delta's title");
    expect(screen.getByRole("radio", { name: "Nile Parts" })).toBeChecked();
    expect(screen.getByRole("link", { name: "View at Nile Parts" })).toBeInTheDocument();
    // The open tab, clicked, picks its shop even though it is already checked.
    fireEvent.click(screen.getByRole("radio", { name: "Nile Parts" }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Nile's title");
  });

  it("a modified click opens the link as a link", () => {
    render(<Page />);
    const link = screen.getByRole("link", { name: "View Volt Corner’s listing on this page" });
    fireEvent.click(link, { ctrlKey: true });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Nile's title");
  });

  it("renders a linked shop's view as it is", () => {
    nav.shop = "volt-corner";
    render(<Page initial="o-volt" explicit />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Volt's title");
    expect(screen.getByRole("radio", { name: "Volt Corner" })).toBeChecked();
  });

  it("a tab click picks once, closed or open", () => {
    render(<Page />);
    fireEvent.click(screen.getByRole("radio", { name: "Volt Corner" }));
    expect(replace).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: "Volt Corner" }));
    expect(replace).toHaveBeenCalledTimes(2);
  });

  it("shows the URL's shop when it is not the one the server rendered (Back)", () => {
    // Next restores the first render (Nile's) under a URL a pick rewrote.
    nav.shop = "volt-corner";
    window.history.replaceState(null, "", "/products/p-ai?shop=volt-corner");
    replace.mockClear();
    render(<Page />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Volt's title");
    expect(row("Volt Corner")).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("radio", { name: "Volt Corner" })).toBeChecked();
    expect(screen.getByRole("link", { name: "View at Volt Corner" })).toBeInTheDocument();
    // Restored, not picked: nothing announced, the URL left as it is.
    expect(screen.getByRole("status")).toHaveTextContent("");
    expect(replace).not.toHaveBeenCalled();
  });

  it("follows `?shop=` when it changes under a mounted page", () => {
    const { rerender } = render(<Page />);
    nav.shop = "volt-corner";
    rerender(<Page />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Volt's title");
    // A shop the page does not have changes nothing.
    nav.shop = "no-such-shop";
    rerender(<Page />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Volt's title");
  });

  it("an offer with no shop takes `?shop=` out of the URL", () => {
    window.history.replaceState(null, "", "/products/p-ai?shop=nile-parts&x=1");
    replace.mockClear();
    const meta: Record<string, PickMeta> = {
      ...META,
      "o-loose": { ...META["o-delta"], slug: null, shop: "Unknown shop", title: "Loose title" },
    };
    render(
      <ShopViewProvider
        initial="o-nile"
        explicit={false}
        primary="o-nile"
        meta={meta}
        leads={LEADS}
      >
        <ShopTitle fallback="TB6600" />
        <div role="radiogroup" aria-label="What the shops say">
          <label>
            <PickerRadio index={0} offer="o-nile" />
            Nile Parts
          </label>
          <label>
            <PickerRadio index={1} offer="o-loose" />
            Unknown shop
          </label>
        </div>
      </ShopViewProvider>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Unknown shop" }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Loose title");
    expect(replace).toHaveBeenCalledWith(null, "", "/products/p-ai?x=1");
  });
});

describe("the AI badge", () => {
  it("is a button named for what it means, its popover opened by a click or tap", async () => {
    render(<AiBadge />);
    const badge = screen.getByRole("button", { name: AI_LABEL });
    expect(badge).toHaveTextContent("AI");
    expect(badge.querySelector("svg[data-sparkles]")).not.toBeNull();
    fireEvent.click(badge);
    expect(await screen.findByText(AI_EXPLAINED)).toBeInTheDocument();
    expect(screen.getByText("Matched by AI")).toBeInTheDocument();
    // Information only: focus stays on the badge.
    expect(badge).toHaveAttribute("aria-expanded", "true");
  });

  it("opens from the keyboard and Esc closes it", async () => {
    render(<AiBadge />);
    const badge = screen.getByRole("button", { name: AI_LABEL });
    act(() => badge.focus());
    fireEvent.keyDown(badge, { key: "Enter" });
    fireEvent.click(badge);
    expect(await screen.findByText(AI_EXPLAINED)).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement ?? badge, { key: "Escape" });
    await waitFor(() => expect(badge).toHaveAttribute("aria-expanded", "false"));
  });

  it("the tab's pill is hidden from screen readers, with its tooltip", () => {
    const { container } = render(<AiPill />);
    const pill = container.querySelector("[data-ai-pill]")!;
    expect(pill).toHaveAttribute("aria-hidden", "true");
    expect(pill.getAttribute("title")).toContain("Matched by AI");
  });
});

const CONTEXT: ReportContext = {
  productId: "p-ai",
  title: "TB6600 Stepper Motor Driver",
  category: null,
  page: "https://makhzan.test/products/p-ai",
  offers: [
    {
      id: "o-nile",
      title: "Nile's title",
      shop: { slug: "nile-parts", name: "Nile Parts" },
      price: "EGP 385",
      outOfStock: false,
      stale: false,
      ai: false,
    },
    {
      id: "o-volt",
      title: "Volt's title",
      shop: { slug: "volt-corner", name: "Volt Corner" },
      price: "EGP 410",
      outOfStock: false,
      stale: false,
      ai: true,
    },
    {
      id: "o-oasis",
      title: "Oasis's title",
      shop: { slug: "oasis-lab", name: "Oasis Lab" },
      price: "EGP 450",
      outOfStock: false,
      stale: false,
      ai: true,
    },
  ],
};

describe("the AI note", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ token: "t" }), { status: 200 })),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("is not there without an AI-matched offer", () => {
    const { container } = render(<AiNote count={0} total={3} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says how many, and “tell us” opens the report on the AI-matched offers, none ticked", async () => {
    render(
      <>
        <AiNote count={2} total={3} />
        <ReportProblem context={CONTEXT} />
      </>,
    );
    const note = screen.getByText(/2 of 3 offers were matched automatically by AI\./);
    expect(note).toHaveTextContent("If one isn’t the same product, tell us.");
    fireEvent.click(screen.getByRole("button", { name: "tell us" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Step 2 of 2")).toBeInTheDocument();
    expect(within(dialog).getByText("These offers aren’t the same product")).toBeInTheDocument();
    const boxes = within(dialog).getAllByRole("checkbox");
    expect(boxes.map((box) => (box as HTMLInputElement).value)).toEqual([
      "o-volt",
      "o-oasis",
      "o-nile",
    ]);
    expect(boxes.every((box) => !(box as HTMLInputElement).checked)).toBe(true);
    expect(within(dialog).getByText(/The ones matched by AI come first\./)).toBeInTheDocument();
    expect(within(dialog).getAllByText("· matched by AI", { exact: false })).toHaveLength(2);
  });
});
