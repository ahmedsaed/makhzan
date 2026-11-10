/**
 * How a shop's contact details read and link: numbers formatted for an
 * Egyptian reader but dialled in E.164, the line naming only what is still
 * missing, where each detail came from (never calling a Google Maps listing
 * the shop's own), the product page's contact blocks, and "Something wrong?".
 */
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopContactSection } from "@/app/(site)/shops/_components/shop-contact";
import { ContactButtons, ReportLink, ShopContactList } from "@/components/contact-links";
import type { ContactSource, ShopContact } from "@/lib/api";
import {
  addressLine,
  daySpan,
  formatCheckedOn,
  formatPhone,
  missingLine,
  possessive,
  provenanceDetails,
  provenanceLine,
  registrableDomain,
  reportHref,
  sourceLabel,
  telHref,
  whatsappHref,
} from "@/lib/contact";

const EMPTY: ShopContact = {
  phones: [],
  whatsapp: null,
  email: null,
  address: null,
  area: null,
  governorate: null,
  maps_url: null,
  opening_hours: [],
  branches: [],
  sources: [],
};

const FULL: ShopContact = {
  phones: ["+20223456789", "+20223456780"],
  whatsapp: "+201001234567",
  email: "sales@shop-a.test",
  address: "12 Example Street",
  area: "Bab El Louk",
  governorate: "Cairo",
  maps_url: "https://maps.app.goo.gl/shopA",
  opening_hours: ["Saturday to Thursday 10:00 to 22:00", "Friday closed"],
  branches: [
    {
      name: "Giza branch",
      address: "3 Other Street",
      area: "Dokki",
      governorate: "Giza",
      phones: ["+20233334444"],
      maps_url: null,
    },
  ],
  sources: [
    {
      origin: "listed",
      url: "https://www.shop-a.test/contact-us",
      checked_on: "2026-11-03",
      fields: ["phones", "email", "address", "area", "governorate", "maps_url", "branches"],
    },
    {
      origin: "read",
      url: "https://www.shop-a.test/",
      checked_on: "2026-11-08",
      fields: ["whatsapp", "opening_hours"],
    },
  ],
};

const PAGE = "https://makhzan.test/shops/shop-a";

function source(url: string | null, fields: string[], extra: Partial<ContactSource> = {}) {
  return { origin: "listed" as const, url, checked_on: "2026-11-10", fields, ...extra };
}

describe("phone numbers", () => {
  it.each([
    ["+201001234567", "010 0123 4567"],
    ["+201551234567", "015 5123 4567"],
    ["+20223456789", "02 2345 6789"],
    ["+2031234567", "03 123 4567"],
    ["+20401234567", "040 123 4567"],
    ["+20133221234", "013 322 1234"],
    ["+20154361234", "015 436 1234"],
    ["19123", "19123"],
    ["16789", "16789"],
    ["+442079460000", "+442079460000"],
  ])("%s reads as %s", (number, text) => {
    expect(formatPhone(number)).toBe(text);
  });

  it("links in E.164, which dials from anywhere", () => {
    expect(telHref("+201001234567")).toBe("tel:+201001234567");
    expect(telHref("19123")).toBe("tel:19123");
    expect(telHref("12345")).toBeNull();
    expect(telHref("2345 6789")).toBeNull();
    expect(whatsappHref("+201001234567")).toBe("https://wa.me/201001234567");
    // A hotline has no WhatsApp.
    expect(whatsappHref("19123")).toBeNull();
  });
});

describe("what is still missing", () => {
  it("names everything for a shop nobody has found details for", () => {
    expect(missingLine(null)).toBe("Address, phone and opening hours aren't listed yet.");
    expect(missingLine(EMPTY)).toBe("Address, phone and opening hours aren't listed yet.");
  });

  it("names only what is missing", () => {
    expect(missingLine({ ...EMPTY, address: "12 Example Street" })).toBe(
      "Phone and opening hours aren't listed yet.",
    );
    expect(missingLine({ ...FULL, opening_hours: [] })).toBe("Opening hours aren't listed yet.");
    expect(missingLine({ ...FULL, address: null, branches: [] })).toBe("Address isn't listed yet.");
  });

  it("counts WhatsApp as a phone, and a branch's address and number", () => {
    expect(
      missingLine({
        ...EMPTY,
        whatsapp: "+201001234567",
        opening_hours: ["Daily 10-22"],
        branches: FULL.branches,
      }),
    ).toBeNull();
  });

  it("an area alone is not an address", () => {
    expect(missingLine({ ...EMPTY, area: "Bab El Louk" })).toMatch(/^Address, phone/);
  });

  it("says nothing when nothing is missing", () => {
    expect(missingLine(FULL)).toBeNull();
  });
});

describe("naming a source", () => {
  it("is the shop's website when either domain is a subdomain of the other", () => {
    const site = "https://store.volt-corner.com";
    expect(sourceLabel("https://volt-corner.com/contact", "Volt", site)).toBe("Volt's website");
    expect(sourceLabel("https://store.volt-corner.com/pages/contact-us", "Volt", site)).toBe(
      "Volt's website",
    );
    expect(sourceLabel("https://store.volt-corner.com/x", "Volt", "https://volt-corner.com")).toBe(
      "Volt's website",
    );
    expect(registrableDomain("www.shop.com.eg")).toBe("shop.com.eg");
    // A different shop under the same public suffix is not this shop.
    expect(sourceLabel("https://other.com.eg/", "Shop", "https://shop.com.eg")).toBe(
      "other.com.eg",
    );
  });

  it("is Google Maps, in every form, and never the shop's", () => {
    for (const url of [
      "https://www.google.com/maps/place/Nile+Parts",
      "https://www.google.com.eg/maps/place/x",
      "https://maps.google.com/?q=x",
      "https://maps.app.goo.gl/AbCdEf123",
      "https://goo.gl/maps/abc",
      "https://g.page/example-shop?share",
    ]) {
      expect(sourceLabel(url, "Nile Parts", "https://nile-parts.com"), url).toBe("Google Maps");
    }
    expect(sourceLabel("https://www.google.com/search?q=x", "A", null)).toBe("google.com");
  });

  it("is Facebook or Instagram, else the host", () => {
    expect(sourceLabel("https://www.facebook.com/shopa", "Shop A", null)).toBe("Facebook");
    expect(sourceLabel("https://m.facebook.com/shopa", "Shop A", null)).toBe("Facebook");
    expect(sourceLabel("https://www.instagram.com/shopa", "Shop A", null)).toBe("Instagram");
    expect(sourceLabel("https://linktr.ee/shopa", "Shop A", null)).toBe("linktr.ee");
  });

  it("writes the possessive the English way", () => {
    expect(possessive("Shop A")).toBe("Shop A's");
    expect(possessive("Nile Parts")).toBe("Nile Parts'");
    expect(possessive("Volt Bits")).toBe("Volt Bits'");
  });
});

const NOW = new Date("2026-11-12T12:00:00Z");

describe("where the details came from, in one short line", () => {
  it("one source", () => {
    const contact = { ...EMPTY, sources: [source("https://shop-a.test/contact", ["phones"])] };
    expect(provenanceLine(contact, "Shop A", "https://shop-a.test", NOW)).toBe(
      "From Shop A's website, checked 10 Nov",
    );
  });

  it("names each place once, a site and an unclaimed Google Maps listing", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://nile-parts.com/contact-us/", ["phones", "whatsapp", "email"]),
        source("https://www.google.com/maps/place/Nile+Parts", ["address", "area", "governorate"]),
        source("https://nile-parts.com/", ["opening_hours"], {
          origin: "read",
          checked_on: "2026-11-09",
        }),
      ],
    };
    expect(provenanceLine(contact, "Nile Parts", "https://nile-parts.com", NOW)).toBe(
      "From Nile Parts' website and Google Maps, checked 9–10 Nov",
    );
  });

  it("spans days across months and years, with the year only when it is not this one", () => {
    expect(daySpan(["2026-11-10"], NOW)).toBe("10 Nov");
    expect(daySpan(["2026-11-10", "2026-11-09", "2026-11-10"], NOW)).toBe("9–10 Nov");
    expect(daySpan(["2026-10-28", "2026-11-10"], NOW)).toBe("28 Oct – 10 Nov");
    expect(daySpan(["2025-12-28", "2026-01-03"], new Date("2026-01-05T00:00:00Z"))).toBe(
      "28 Dec 2025 – 3 Jan",
    );
    expect(daySpan(["2025-11-03"], NOW)).toBe("3 Nov 2025");
    expect(daySpan(["2025-11-03", "2025-11-05"], NOW)).toBe("3–5 Nov 2025");
    expect(daySpan(["garbage"], NOW)).toBeNull();
  });

  it("without a page, says only when; without either, nothing", () => {
    const when = { ...EMPTY, sources: [source(null, ["phones"])] };
    expect(provenanceLine(when, "Shop A", null, NOW)).toBe("Checked 10 Nov");
    const neither = { ...EMPTY, sources: [source(null, ["area"], { checked_on: null })] };
    expect(provenanceLine(neither, "Shop A", null, NOW)).toBeNull();
    expect(provenanceLine(EMPTY, "Shop A", null, NOW)).toBeNull();
    expect(formatCheckedOn("garbage")).toBeNull();
  });
});

describe("where each detail came from, for the Sources disclosure", () => {
  it("one line a place, a way of reading and a day; Google Maps never the shop's", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://nile-parts.com/contact-us/", ["phones", "whatsapp", "email"]),
        source("https://maps.app.goo.gl/x", ["address", "area", "governorate", "maps_url"]),
        source("https://nile-parts.com/", ["opening_hours"], {
          origin: "read",
          checked_on: "2026-11-09",
        }),
      ],
    };
    expect(provenanceDetails(contact, "Nile Parts", "https://nile-parts.com")).toEqual([
      "Phone, WhatsApp and email from Nile Parts' website, checked 10 Nov 2026",
      "Opening hours from Nile Parts' website, read automatically 9 Nov 2026",
      "Address and map link from Google Maps, checked 10 Nov 2026",
    ]);
  });

  it("two pages of one site on one day are one place", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://shop-a.test/contact", ["phones"]),
        source("https://shop-a.test/about", ["address"]),
      ],
    };
    expect(provenanceDetails(contact, "Shop A", "https://shop-a.test")).toEqual([
      "Phone and address from Shop A's website, checked 10 Nov 2026",
    ]);
  });

  it("names Facebook as such, and a source with no page by its day alone", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://www.facebook.com/shopa", ["phones"], { checked_on: "2026-11-01" }),
        source(null, ["email"]),
      ],
    };
    expect(provenanceDetails(contact, "Shop A", "https://shop-a.test")).toEqual([
      "Phone from Facebook, checked 1 Nov 2026",
      "Email, checked 10 Nov 2026",
    ]);
  });
});

describe("an address on one line", () => {
  it("leaves out the places the page already shows", () => {
    expect(
      addressLine("12 Example Street", ["Bab El Louk", "Cairo"], ["Bab El Louk", "Cairo"]),
    ).toBe("12 Example Street");
    expect(addressLine("12 Example Street", ["Dokki", "Giza"], ["Bab El Louk", "Cairo"])).toBe(
      "12 Example Street, Dokki, Giza",
    );
  });

  it("leaves out a place the address already names, as whole words only", () => {
    expect(addressLine("4 Nile Road, Garden Heights, Smouha", ["Smouha", "Alexandria"])).toBe(
      "4 Nile Road, Garden Heights, Smouha, Alexandria",
    );
    expect(addressLine("4 Nile Road, Garden Heights", ["Garden", "Alexandria"])).toBe(
      "4 Nile Road, Garden Heights, Alexandria",
    );
    expect(addressLine("4 Nile Road, Gardenia", ["Garden", null])).toBe(
      "4 Nile Road, Gardenia, Garden",
    );
  });

  it("is the places alone without an address, and empty with nothing", () => {
    expect(addressLine(null, ["Dokki", "Giza"])).toBe("Dokki, Giza");
    expect(addressLine(null, [null, "Giza"], ["Giza"])).toBe("");
  });
});

describe("Something wrong? Tell us", () => {
  it("emails makhzan, naming the shop and the product", () => {
    const href = reportHref({ shop: "Shop A", product: "LM358", page: PAGE });
    const url = new URL(href);
    expect(url.protocol).toBe("mailto:");
    expect(url.pathname).toBe("crawler@makhzan.merope.dev");
    expect(decodeURIComponent(href)).toContain("subject=Something wrong: LM358 at Shop A");
    expect(decodeURIComponent(href)).toContain("What is wrong, and what should it say?");
    expect(decodeURIComponent(href)).toContain(`Page: ${PAGE}`);
    expect(decodeURIComponent(reportHref({ shop: "Shop A", page: PAGE }))).toContain(
      "subject=Something wrong: Shop A&",
    );
  });

  it("is a contact link, counted and untagged", () => {
    const { getByRole } = render(<ReportLink shop="shop-a" shopName="Shop A" page={PAGE} />);
    const link = getByRole("link", { name: "Tell us" });
    expect(link).toHaveAttribute("data-contact", "report");
    expect(link).toHaveAttribute("data-umami-event", "shop-contact");
    expect(link.getAttribute("href")).toMatch(/^mailto:crawler@makhzan\.merope\.dev\?subject=/);
  });
});

describe("the shop page's contact section", () => {
  function renderFull(contact: ShopContact = FULL) {
    return render(
      <ShopContactSection
        contact={contact}
        shop="shop-a"
        shopName="Shop A"
        websiteUrl="https://shop-a.test"
        page={PAGE}
        shownPlace={["Bab El Louk", "Cairo"]}
        now={NOW}
      />,
    );
  }

  it("a call button per number, then WhatsApp and Email, all the same button", () => {
    const { container, getByRole } = renderFull();
    const buttons = [...container.querySelectorAll("[data-contact-actions] a")];
    expect(buttons.map((a) => a.getAttribute("data-contact"))).toEqual([
      "phone",
      "phone",
      "whatsapp",
      "email",
    ]);
    const call = getByRole("link", { name: "Call Shop A on 02 2345 6789" });
    expect(call).toHaveAttribute("href", "tel:+20223456789");
    const other = getByRole("link", { name: "Call Shop A on 02 2345 6780" });
    expect(other).toHaveAttribute("href", "tel:+20223456780");
    // The second number is the same button as the first, not a text link beside
    // it; with several numbers the icon says "call", so the word is hidden.
    expect(other.className).toBe(call.className);
    expect(container.querySelector("[data-contact-actions]")).not.toHaveTextContent(/\bor\b/);
    for (const button of [call, other]) {
      expect(button.querySelector(".tabular > span")).toHaveClass("hidden");
    }
    const whatsapp = getByRole("link", { name: "WhatsApp Shop A on 010 0123 4567" });
    expect(whatsapp).toHaveAttribute("href", "https://wa.me/201001234567");
    expect(whatsapp).toHaveAttribute("target", "_blank");
    expect(getByRole("link", { name: "Email Shop A at sales@shop-a.test" })).toHaveAttribute(
      "href",
      "mailto:sales@shop-a.test",
    );
  });

  it("the address on one line, without the area the header shows, then the map", () => {
    const { container, getByRole } = renderFull();
    const address = container.querySelector('[data-contact-line="address"]');
    expect(address).toHaveTextContent(/^Main shop: 12 Example Street · Open in maps$/);
    expect(getByRole("link", { name: "Map: Shop A, Bab El Louk, Cairo" })).toHaveAttribute(
      "href",
      "https://maps.app.goo.gl/shopA",
    );
  });

  it("a branch on one compact line, its own place kept, its number saying which branch", () => {
    const { container, getByRole } = renderFull();
    expect(container.querySelector('[data-contact-line="branch"]')).toHaveTextContent(
      /^Giza branch: 3 Other Street, Dokki, Giza · 02 3333 4444$/,
    );
    expect(getByRole("link", { name: "Call Shop A Giza branch on 02 3333 4444" })).toHaveAttribute(
      "href",
      "tel:+20233334444",
    );
  });

  it("hours in plain English, or as written", () => {
    const { container } = renderFull({
      ...FULL,
      opening_hours: ["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"],
    });
    expect(container.querySelector("[data-opening-hours]")).toHaveTextContent(
      "Opening hours: Sat–Thu 10:00–20:30 · Fri 14:00–20:00",
    );
    const written = renderFull();
    expect(written.container.querySelector("[data-opening-hours]")).toHaveTextContent(
      "Saturday to Thursday 10:00 to 22:00 · Friday closed",
    );
  });

  it("one short source line beside the report link, the breakdown behind Sources", () => {
    const { container, getByRole } = renderFull();
    expect(container.querySelector("[data-contact-source]")).toHaveTextContent(
      "From Shop A's website, checked 3–8 Nov (sources)",
    );
    const sources = container.querySelector("details[data-contact-sources]");
    expect(sources).not.toHaveAttribute("open");
    expect([...(sources?.querySelectorAll("li") ?? [])].map((li) => li.textContent)).toEqual([
      "Phone, email, address, map link and branches from Shop A's website, checked 3 Nov 2026",
      "WhatsApp and opening hours from Shop A's website, read automatically 8 Nov 2026",
    ]);
    expect(getByRole("link", { name: "Tell us" })).toHaveAttribute("data-contact", "report");
    // Every link is a contact link, counted, none tagged as a visit (P4's exception).
    for (const link of container.querySelectorAll("a")) {
      expect(link).toHaveAttribute("data-umami-event", "shop-contact");
      expect(link.getAttribute("href")).not.toContain("ref=makhzan");
    }
  });

  it("a shop with only a map link and one number", () => {
    const { container } = renderFull({
      ...EMPTY,
      phones: ["+201001234567"],
      maps_url: "https://maps.app.goo.gl/x",
      sources: [source("https://shop-a.test/contact", ["phones", "maps_url"])],
    });
    expect(container.querySelector('[data-contact-line="address"]')).toHaveTextContent(
      /^Open in maps$/,
    );
    expect(container.querySelector("[data-opening-hours]")).toBeNull();
    expect(container.querySelectorAll("[data-contact-actions] a")).toHaveLength(1);
  });

  it("renders nothing for an empty block", () => {
    const { container } = render(
      <ShopContactSection
        contact={EMPTY}
        shop="shop-a"
        shopName="Shop A"
        websiteUrl={null}
        page={PAGE}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("contacting the shops from a product page", () => {
  it("one shop: a call, WhatsApp and email, whichever it publishes, then its hours", () => {
    const { container, getByRole, getAllByRole } = render(
      <ContactButtons
        reach={{ phone: "+20223456789", whatsapp: "+201001234567", email: null }}
        shop="shop-a"
        shopName="Shop A"
        hours={["Mo-Fr 09:00-17:00"]}
      />,
    );
    expect(getAllByRole("link").map((a) => a.getAttribute("data-contact"))).toEqual([
      "phone",
      "whatsapp",
    ]);
    expect(getByRole("link", { name: "WhatsApp Shop A on 010 0123 4567" })).toHaveAttribute(
      "href",
      "https://wa.me/201001234567",
    );
    const call = getByRole("link", { name: "Call Shop A on 02 2345 6789" });
    expect(call).toHaveAttribute("href", "tel:+20223456789");
    expect(call).toHaveTextContent("Call 02 2345 6789");
    expect(container.querySelector("[data-opening-hours]")).toHaveTextContent(
      "Mon–Fri 09:00–17:00 · Sat, Sun closed",
    );
  });

  it("several shops: a block a shop that can be reached, with its hours", () => {
    const { container, getByRole } = render(
      <ShopContactList
        shops={[
          {
            slug: "nile",
            name: "Nile Parts",
            reach: { phone: "19123", whatsapp: null, email: null },
            hours: ["Sa-Th 10:00-22:00"],
          },
          { slug: "delta", name: "Delta Bench", reach: null },
          {
            slug: "volt",
            name: "Volt Corner",
            reach: { phone: null, whatsapp: "+201001234567", email: "a@volt.test" },
          },
        ]}
      />,
    );
    const lines = container.querySelectorAll("[data-shop-contact-line]");
    expect([...lines].map((l) => l.getAttribute("data-shop-contact-line"))).toEqual([
      "nile",
      "volt",
    ]);
    expect(getByRole("link", { name: "Call Nile Parts on 19123" })).toHaveAttribute(
      "href",
      "tel:19123",
    );
    expect(lines[0]).toHaveTextContent(
      "Nile PartsCall 19123Opening hours: Sat–Thu 10:00–22:00 · Fri closed",
    );
    expect(lines[1]).toHaveTextContent(/^Volt CornerWhatsApp · Email$/);
    expect(getByRole("link", { name: "Email Volt Corner at a@volt.test" })).toHaveAttribute(
      "href",
      "mailto:a@volt.test",
    );
  });

  it("renders nothing when no shop can be reached", () => {
    for (const reach of [null, undefined, { phone: null, whatsapp: null, email: null }]) {
      const { container } = render(<ContactButtons reach={reach} shop="a" shopName="A" />);
      expect(container).toBeEmptyDOMElement();
    }
    const { container } = render(
      <ShopContactList shops={[{ slug: "a", name: "A", reach: null }]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
