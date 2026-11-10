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
  formatCheckedOn,
  formatPhone,
  missingLine,
  possessive,
  provenance,
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

describe("where the details came from, in one sentence", () => {
  it("one source", () => {
    const contact = { ...EMPTY, sources: [source("https://shop-a.test/contact", ["phones"])] };
    expect(provenance(contact, "Shop A", "https://shop-a.test")).toBe(
      "From Shop A's website, checked 10 Nov 2026.",
    );
  });

  it("a site and an unclaimed Google Maps listing, checked the same day", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://nile-parts.com/contact-us/", ["phones", "whatsapp", "email"]),
        source("https://www.google.com/maps/place/Nile+Parts", ["address", "area", "governorate"]),
      ],
    };
    expect(provenance(contact, "Nile Parts", "https://nile-parts.com")).toBe(
      "Phone, WhatsApp and email from Nile Parts' website and address from Google Maps, all checked 10 Nov 2026.",
    );
  });

  it("names the shop's website once, with what was checked and what was read", () => {
    expect(provenance(FULL, "Shop A", "https://shop-a.test")).toBe(
      "Phone, email, address, map link and branches from Shop A's website, checked 3 Nov 2026, and WhatsApp and opening hours read automatically 8 Nov 2026.",
    );
  });

  it("two pages of one site on one day are one place", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://shop-a.test/contact", ["phones"]),
        source("https://shop-a.test/about", ["address"]),
      ],
    };
    expect(provenance(contact, "Shop A", "https://shop-a.test")).toBe(
      "From Shop A's website, checked 10 Nov 2026.",
    );
  });

  it("different places on different days", () => {
    const contact = {
      ...EMPTY,
      sources: [
        source("https://www.facebook.com/shopa", ["phones"], { checked_on: "2026-11-01" }),
        source("https://maps.app.goo.gl/x", ["address", "maps_url"]),
      ],
    };
    expect(provenance(contact, "Shop A", "https://shop-a.test")).toBe(
      "Phone from Facebook, checked 1 Nov 2026; address and map link from Google Maps, checked 10 Nov 2026.",
    );
  });

  it("is null when no source says where or when", () => {
    const contact = { ...EMPTY, sources: [source(null, ["area"], { checked_on: null })] };
    expect(provenance(contact, "Shop A", null)).toBeNull();
    expect(provenance(EMPTY, "Shop A", null)).toBeNull();
    expect(formatCheckedOn("garbage")).toBeNull();
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
  it("links every number, WhatsApp, email and map, and says where they came from", () => {
    const { container, getByRole, getByText } = render(
      <ShopContactSection
        contact={FULL}
        shop="shop-a"
        shopName="Shop A"
        websiteUrl="https://shop-a.test"
        page={PAGE}
      />,
    );
    expect(getByRole("link", { name: "Call Shop A on 02 2345 6789" })).toHaveAttribute(
      "href",
      "tel:+20223456789",
    );
    expect(getByRole("link", { name: "Call Shop A on 02 2345 6780" })).toBeInTheDocument();
    // A branch's number says which branch it rings.
    expect(
      getByRole("link", { name: "Call Shop A Giza branch on 02 3333 4444" }),
    ).toBeInTheDocument();
    const whatsapp = getByRole("link", { name: "WhatsApp Shop A on 010 0123 4567" });
    expect(whatsapp).toHaveAttribute("href", "https://wa.me/201001234567");
    expect(whatsapp).toHaveAttribute("target", "_blank");
    expect(getByRole("link", { name: "sales@shop-a.test" })).toHaveAttribute(
      "href",
      "mailto:sales@shop-a.test",
    );
    expect(getByRole("link", { name: "Map: Shop A, Bab El Louk, Cairo" })).toHaveAttribute(
      "href",
      "https://maps.app.goo.gl/shopA",
    );
    expect(getByText("Main shop")).toBeInTheDocument();
    expect(getByText("Friday closed")).toBeInTheDocument();
    expect(container.querySelector("[data-contact-source]")).toHaveTextContent(
      /^Phone, email, address, map link and branches from Shop A's website/,
    );
    expect(getByRole("link", { name: "Tell us" })).toHaveAttribute("data-contact", "report");
    // Every link is a contact link, counted, none tagged as a visit (P4's exception).
    for (const link of container.querySelectorAll("a")) {
      expect(link).toHaveAttribute("data-umami-event", "shop-contact");
      expect(link.getAttribute("href")).not.toContain("ref=makhzan");
    }
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
  it("one shop: WhatsApp, a call and email, whichever it publishes", () => {
    const { getByRole, getAllByRole } = render(
      <ContactButtons
        reach={{ phone: "+20223456789", whatsapp: "+201001234567", email: null }}
        shop="shop-a"
        shopName="Shop A"
      />,
    );
    expect(getAllByRole("link")).toHaveLength(2);
    expect(getByRole("link", { name: "WhatsApp Shop A" })).toHaveAttribute(
      "href",
      "https://wa.me/201001234567",
    );
    const call = getByRole("link", { name: "Call Shop A on 02 2345 6789" });
    expect(call).toHaveAttribute("href", "tel:+20223456789");
    expect(call).toHaveTextContent("Call 02 2345 6789");
  });

  it("several shops: one line a shop that can be reached", () => {
    const { container, getByRole } = render(
      <ShopContactList
        shops={[
          {
            slug: "nile",
            name: "Nile Parts",
            reach: { phone: "19123", whatsapp: null, email: null },
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
    expect(getByRole("link", { name: "Email Volt Corner" })).toHaveAttribute(
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
