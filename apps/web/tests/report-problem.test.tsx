/**
 * The "Report a problem" dialog in jsdom: every state the mockup draws, what
 * it sends, and the focus rules (opening, Esc, back to the button). The
 * browser-level checks (phone and desktop, keyboard, layout) are in
 * tests/e2e/report.spec.ts.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import { ReportProblem } from "@/components/report-problem";
import type { ReportContext } from "@/lib/report";

const CONTEXT: ReportContext = {
  productId: "6f1c2a9e-3b7d-4c51-9a0e-2d8f61b4c7a3",
  title: "TB6600 Stepper Motor Driver 4A",
  category: "Electronic components › Motor control › Stepper drivers",
  page: "https://makhzan.test/products/6f1c2a9e-3b7d-4c51-9a0e-2d8f61b4c7a3",
  offers: [
    {
      id: "o-delta",
      title: "TB6600 Stepper Motor Driver 4A 9-42V",
      shop: { slug: "delta-components", name: "Delta Components" },
      price: "EGP 425",
      outOfStock: false,
      stale: false,
    },
    {
      id: "o-bazaar",
      title: "TB6600 4A Stepper Driver Module",
      shop: { slug: "bazaar-hub", name: "Bazaar Hub" },
      price: "EGP 504",
      outOfStock: true,
      stale: false,
    },
  ],
};

/** What the form sends: always a method and a JSON body. */
type Init = { method?: string; body: string };
let fetchMock: Mock<(url: string, init: Init) => Promise<Response>>;
let tokenMock: Mock<(url: string) => Promise<Response>>;
let clock = 0;

beforeEach(() => {
  fetchMock = vi.fn();
  tokenMock = vi.fn(async () => reply(200, { token: "tok-1" }));
  // The opened-at token is answered here; everything else is the test's.
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
    String(url).endsWith("/reports/token") ? tokenMock(url) : fetchMock(url, init as Init),
  );
  clock = 0;
  vi.spyOn(performance, "now").mockImplementation(() => clock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function reply(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

async function openDialog(context = CONTEXT) {
  render(<ReportProblem context={context} />);
  const button = screen.getByRole("button", { name: "Report a problem" });
  fireEvent.click(button);
  const dialog = await screen.findByRole("dialog");
  return { button, dialog };
}

async function toStepTwo(reason: RegExp) {
  const { button, dialog } = await openDialog();
  fireEvent.click(within(dialog).getByRole("radio", { name: reason }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
  await within(dialog).findByText("Step 2 of 2");
  return { button, dialog };
}

describe("the button", () => {
  it("is a button with a flag and its label, never a link", () => {
    render(<ReportProblem context={CONTEXT} />);
    const button = screen.getByRole("button", { name: "Report a problem" });
    expect(button.tagName).toBe("BUTTON");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(button).toHaveTextContent("Report a problem");
    // The flag alone on a phone: the label hides below `sm`, the name stays.
    expect(button.querySelector("span")).toHaveClass("max-sm:hidden");
    expect(button).toHaveClass("max-sm:w-11", "min-h-11");
  });
});

describe("opening and closing", () => {
  it("opens on the question, named by its title", async () => {
    const { dialog } = await openDialog();
    expect(dialog).toHaveAccessibleName("Report a problem");
    expect(within(dialog).getByText(CONTEXT.title)).toBeInTheDocument();
    await waitFor(() =>
      expect(within(dialog).getByRole("heading", { name: "What’s wrong?" })).toHaveFocus(),
    );
  });

  it("closes on Esc and gives focus back to the button", async () => {
    const { button, dialog } = await openDialog();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(button).toHaveFocus());
  });

  it("closes on Cancel and on the close button", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Report a problem" }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Close" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("keeps a draft that was not sent", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.change(within(dialog).getByLabelText(/Where should it be/), {
      target: { value: "Motor drivers" },
    });
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Report a problem" }));
    const again = await screen.findByRole("dialog");
    expect(within(again).getByLabelText(/Where should it be/)).toHaveValue("Motor drivers");
  });
});

describe("step 1", () => {
  it("lists every reason, comparing offers only with several", async () => {
    const { dialog } = await openDialog();
    expect(within(dialog).getAllByRole("radio")).toHaveLength(7);
    expect(within(dialog).getByText("Step 1 of 2")).toBeInTheDocument();
  });

  it("drops 'not the same product' on a one-offer page", async () => {
    const { dialog } = await openDialog({ ...CONTEXT, offers: [CONTEXT.offers[0]] });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(6);
    expect(within(dialog).queryByRole("radio", { name: /aren’t the same/ })).toBeNull();
  });

  it("says what is missing, and focuses it", async () => {
    const { dialog } = await openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Continue" }));
    expect(await within(dialog).findByText("Choose what’s wrong to continue.")).toBeVisible();
    await waitFor(() => expect(within(dialog).getAllByRole("radio")[0]).toHaveFocus());
  });
});

describe("step 2", () => {
  it("lists every offer to tick, out of stock included", async () => {
    const { dialog } = await toStepTwo(/aren’t the same/);
    const boxes = within(dialog).getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(within(dialog).getByText(/Bazaar Hub/).textContent).toContain("out of stock");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("heading", { name: "These offers aren’t the same product" }),
      ).toHaveFocus(),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    expect(
      await within(dialog).findByText("Tick at least one offer that is a different product."),
    ).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows price or stock follow-ups for the choice made", async () => {
    const { dialog } = await toStepTwo(/Wrong price or stock/);
    expect(within(dialog).getAllByRole("radio", { name: /TB6600/ })).toHaveLength(2);
    fireEvent.click(within(dialog).getByRole("radio", { name: "The price" }));
    expect(within(dialog).getByLabelText(/Price on the shop’s site/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("radio", { name: "The stock" }));
    expect(within(dialog).getByRole("radio", { name: "No longer listed" })).toBeInTheDocument();
  });

  it("shows where it is filed now", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    expect(within(dialog).getByText(CONTEXT.category!)).toBeInTheDocument();
  });

  it("asks which shop and which detail for contact details", async () => {
    const { dialog } = await toStepTwo(/contact details/);
    expect(within(dialog).getByLabelText("Which shop?")).toBeInTheDocument();
    for (const name of ["Phone", "WhatsApp", "Opening hours", "Address"]) {
      expect(within(dialog).getByRole("radio", { name })).toBeInTheDocument();
    }
  });

  it("needs a few words for 'something else'", async () => {
    const { dialog } = await toStepTwo(/Something else/);
    expect(within(dialog).getByLabelText(/What’s wrong\? \(required\)/)).toBeRequired();
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    expect(await within(dialog).findByText("Tell us what’s wrong, in a few words.")).toBeVisible();
    await waitFor(() => expect(within(dialog).getByLabelText(/What’s wrong\?/)).toHaveFocus());
  });

  it("refuses an incomplete email before sending", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.change(within(dialog).getByLabelText(/Email/), { target: { value: "me@home" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    expect(await within(dialog).findByText(/doesn’t look complete/)).toBeVisible();
    expect(within(dialog).getByLabelText(/Email/)).toHaveAttribute("aria-invalid", "true");
  });

  it("counts the characters", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.change(within(dialog).getByLabelText(/Anything else/), {
      target: { value: "abc" },
    });
    expect(within(dialog).getByText("3 / 1,000")).toBeInTheDocument();
  });

  it("goes back to the reasons", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(await within(dialog).findByText("Step 1 of 2")).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /Wrong category/ })).toBeChecked();
  });

  it("carries a hidden honeypot no one can tab to", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    const trap = dialog.querySelector<HTMLInputElement>('input[name="website"]')!;
    expect(trap).toHaveAttribute("tabindex", "-1");
    expect(trap.closest("[aria-hidden='true']")).not.toBeNull();
  });

  it("links the privacy policy and says what is kept", async () => {
    const { dialog } = await toStepTwo(/Wrong category/);
    const note = dialog.querySelector("[data-report-privacy]")!;
    expect(note.textContent).toMatch(/deleted 90 days after you send it/);
    expect(note.textContent).toMatch(/IP address for 24 hours/);
    expect(within(dialog).getByRole("link", { name: /Privacy policy/ })).toHaveAttribute(
      "href",
      "/privacy",
    );
  });
});

describe("sending", () => {
  it("sends what was chosen, says it is sending, then thanks", async () => {
    let finish: (r: Response) => void = () => {};
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (finish = resolve)));
    const { dialog } = await toStepTwo(/aren’t the same/);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Bazaar Hub/ }));
    fireEvent.change(within(dialog).getByLabelText(/Email/), {
      target: { value: "buyer@example.com" },
    });
    clock = 9000;
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));

    expect(await within(dialog).findByText("Sending…")).toBeInTheDocument();
    expect(within(dialog).getByRole("checkbox", { name: /Bazaar Hub/ })).toBeDisabled();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/reports");
    expect(JSON.parse(init.body)).toMatchObject({
      product_id: CONTEXT.productId,
      reason: "offers_not_same",
      offer_ids: ["o-bazaar"],
      email: "buyer@example.com",
      website: "",
      token: "tok-1",
    });

    await act(async () => finish(reply(202, { reference: "R-24817" })));
    const status = await within(dialog).findByRole("status");
    expect(status).toHaveTextContent("Thanks — we review every report");
    expect(status).toHaveTextContent("teach makhzan’s matching not to repeat it");
    expect(status).toHaveTextContent("We’ll reply to buyer@example.com");
    expect(status).toHaveTextContent("Report R-24817");
    await waitFor(() =>
      expect(within(dialog).getByRole("heading", { name: /Thanks/ })).toHaveFocus(),
    );
    // The footer's Close, beside the header's.
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Close" }).at(-1)!);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // A report that went is done with: the next one starts afresh.
    fireEvent.click(screen.getByRole("button", { name: "Report a problem" }));
    expect(await screen.findByText("Step 1 of 2")).toBeInTheDocument();
  });

  it("says so when no email was left", async () => {
    fetchMock.mockResolvedValue(reply(202, { reference: "R-1" }));
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "You didn’t leave an email",
    );
  });

  it("keeps everything when it could not send, and offers email", async () => {
    fetchMock.mockResolvedValue(reply(500, {}));
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.change(within(dialog).getByLabelText(/Anything else/), {
      target: { value: "It is a motor driver" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Your report wasn’t sent.");
    expect(alert).toHaveTextContent("Nothing you wrote is lost");
    const mail = within(alert).getByRole("link", { name: "email it to us" });
    expect(decodeURIComponent(mail.getAttribute("href")!)).toContain("It is a motor driver");
    expect(within(dialog).getByLabelText(/Anything else/)).toHaveValue("It is a motor driver");
    expect(within(dialog).getByRole("button", { name: "Send report" })).toBeEnabled();
  });

  it("shows 'too many reports' with how long to wait", async () => {
    fetchMock.mockResolvedValue(
      reply(429, { detail: { limit: "hour", count: 5, retry_after_minutes: 40 } }),
    );
    const { dialog } = await toStepTwo(/Something else/);
    fireEvent.change(within(dialog).getByLabelText(/What’s wrong\?/), {
      target: { value: "The page title has a typo." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("You’ve sent 5 reports in the last hour.");
    expect(alert).toHaveTextContent("please wait about 40 minutes");
    expect(alert).toHaveTextContent("Your text is still here.");
    expect(within(dialog).getByLabelText(/What’s wrong\?/)).toHaveValue(
      "The page title has a typo.",
    );
  });
});

describe("the same as another product", () => {
  it("searches makhzan as you type, picks with the keyboard, and sends its id", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.startsWith("/api/search"))
        return reply(200, {
          hits: [
            {
              id: CONTEXT.productId,
              title_en: "This very product",
              title_ar: null,
              part_number: "TB6600",
              supplier_count: 2,
              min_price: 425,
              max_price: 504,
              currency: "EGP",
            },
            {
              id: "other-1",
              title_en: "TB6600 Stepper Driver 4.5A",
              title_ar: null,
              part_number: "TB6600",
              supplier_count: 2,
              min_price: 480,
              max_price: 520,
              currency: "EGP",
            },
          ],
        });
      return reply(202, { reference: "R-3" });
    });
    const { dialog } = await toStepTwo(/same as another product/);
    const combo = within(dialog).getByRole("combobox", { name: /same as/ });
    fireEvent.change(combo, { target: { value: "TB6600" } });
    const option = await within(dialog).findByRole("option", { name: /4\.5A/ });
    // Never this product itself.
    expect(within(dialog).queryByRole("option", { name: /This very product/ })).toBeNull();
    expect(option).toHaveTextContent("2 shops · EGP 480 – 520 · TB6600");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/search?q=TB6600&limit=6");

    fireEvent.keyDown(combo, { key: "ArrowDown" });
    expect(combo).toHaveAttribute("aria-activedescendant", option.id);
    // Esc closes the list, not the dialog.
    fireEvent.keyDown(combo, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(combo).toHaveAttribute("aria-expanded", "false");

    fireEvent.keyDown(combo, { key: "ArrowDown" });
    fireEvent.keyDown(combo, { key: "Enter" });
    const picked = await within(dialog).findByText("TB6600 Stepper Driver 4.5A");
    expect(picked.closest("[data-report-picked]")).not.toBeNull();
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Change the other product" }),
      ).toHaveFocus(),
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    await within(dialog).findByRole("status");
    const sent = fetchMock.mock.calls.find(([url]) => url === "/api/reports")!;
    expect(JSON.parse(sent[1].body)).toMatchObject({
      reason: "same_as_other",
      other_product_id: "other-1",
    });
  });

  it("needs the other product picked", async () => {
    const { dialog } = await toStepTwo(/same as another product/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    expect(
      await within(dialog).findByText("Pick the other product, or paste its makhzan link."),
    ).toBeVisible();
  });
});

describe("the opened-at token", () => {
  it("is asked for when the dialog opens, and once more if that failed", async () => {
    tokenMock.mockResolvedValueOnce(reply(503, {}));
    fetchMock.mockResolvedValue(reply(202, { reference: "R-9" }));
    const { dialog } = await toStepTwo(/Wrong category/);
    expect(tokenMock).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    await within(dialog).findByRole("status");
    expect(tokenMock).toHaveBeenCalledTimes(2);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).token).toBe("tok-1");
  });

  it("says not sent, and sends nothing, when no token can be had", async () => {
    tokenMock.mockResolvedValue(reply(503, {}));
    const { dialog } = await toStepTwo(/Wrong category/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Send report" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Your report wasn’t sent.");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
