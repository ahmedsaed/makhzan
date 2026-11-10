/**
 * How a shop's contact details read and link: numbers formatted for an
 * Egyptian reader but dialled in E.164, the line naming only what is still
 * missing, where the details came from, and the per-offer "Contact" links.
 */
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopContactSection } from "@/app/(site)/shops/_components/shop-contact";
import { ContactLinks } from "@/components/contact-links";
import type { ShopContact } from "@/lib/api";
import {
  formatCheckedOn,
  formatPhone,
  missingLine,
  sourceLines,
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
  maps_url: "https://maps.example/shop-a",
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
      fields: ["phones", "email", "address"],
    },
    {
      origin: "read",
      url: "https://www.shop-a.test/",
      checked_on: "2026-11-08",
      fields: ["whatsapp", "opening_hours"],
    },
  ],
};

describe("phone numbers", () => {
  it.each([
    ["+201001234567", "010 0123 4567"],
    ["+201551234567", "015 5123 4567"],
    ["+20223456789", "02 2345 6789"],
    ["+2031234567", "03 123 4567"],
    ["+20401234567", "040 123 4567"],
    ["19123", "19123"],
    ["+442079460000", "+442079460000"],
  ])("%s reads as %s", (number, text) => {
    expect(formatPhone(number)).toBe(text);
  });

  it("links in E.164, which dials from anywhere", () => {
    expect(telHref("+201001234567")).toBe("tel:+201001234567");
    expect(telHref("19123")).toBe("tel:19123");
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

describe("where the details came from", () => {
  it("names the shop's own website, and how each was checked", () => {
    expect(sourceLines(FULL, "Shop A", "https://shop-a.test")).toEqual([
      "From Shop A's website, checked 3 Nov 2026.",
      "WhatsApp and opening hours read automatically from Shop A's website, 8 Nov 2026.",
    ]);
  });

  it("names another site by its host", () => {
    const contact = {
      ...EMPTY,
      sources: [
        {
          origin: "listed" as const,
          url: "https://www.facebook.com/shop-a",
          checked_on: "2026-11-03",
          fields: [],
        },
      ],
    };
    expect(sourceLines(contact, "Shop A", "https://shop-a.test")).toEqual([
      "From facebook.com, checked 3 Nov 2026.",
    ]);
  });

  it("leaves out a source that says neither where nor when", () => {
    const contact = {
      ...EMPTY,
      sources: [{ origin: "listed" as const, url: null, checked_on: null, fields: ["area"] }],
    };
    expect(sourceLines(contact, "Shop A", null)).toEqual([]);
    expect(formatCheckedOn("garbage")).toBeNull();
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
      />,
    );
    expect(getByRole("link", { name: "Call Shop A on 02 2345 6789" })).toHaveAttribute(
      "href",
      "tel:+20223456789",
    );
    expect(getByRole("link", { name: "Call Shop A on 02 2345 6780" })).toBeInTheDocument();
    expect(getByRole("link", { name: "Call Shop A on 02 3333 4444" })).toBeInTheDocument();
    const whatsapp = getByRole("link", { name: "WhatsApp Shop A on 010 0123 4567" });
    expect(whatsapp).toHaveAttribute("href", "https://wa.me/201001234567");
    expect(whatsapp).toHaveAttribute("target", "_blank");
    expect(getByRole("link", { name: "sales@shop-a.test" })).toHaveAttribute(
      "href",
      "mailto:sales@shop-a.test",
    );
    expect(getByRole("link", { name: "Map: Shop A, Bab El Louk, Cairo" })).toHaveAttribute(
      "href",
      "https://maps.example/shop-a",
    );
    expect(getByText("Main shop")).toBeInTheDocument();
    expect(getByText("Giza branch")).toBeInTheDocument();
    expect(getByText("Friday closed")).toBeInTheDocument();
    expect(container.querySelector("[data-contact-source]")).toHaveTextContent(
      "From Shop A's website, checked 3 Nov 2026.",
    );
    // Every contact link is counted, none is tagged as a visit (P4's exception).
    for (const link of container.querySelectorAll("a")) {
      expect(link).toHaveAttribute("data-umami-event", "shop-contact");
      expect(link.getAttribute("href")).not.toContain("ref=makhzan");
    }
  });

  it("renders nothing for an empty block", () => {
    const { container } = render(
      <ShopContactSection contact={EMPTY} shop="shop-a" shopName="Shop A" websiteUrl={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("an offer's Contact links", () => {
  it("offers WhatsApp, a call and email, whichever the shop publishes", () => {
    const { getByRole, getAllByRole } = render(
      <ContactLinks
        reach={{ phone: "+20223456789", whatsapp: "+201001234567", email: null }}
        shop="shop-a"
        shopName="Shop A"
        variant="inline"
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

  it("renders nothing for a shop with no way to reach it", () => {
    for (const reach of [null, undefined, { phone: null, whatsapp: null, email: null }]) {
      const { container } = render(
        <ContactLinks reach={reach} shop="shop-a" shopName="Shop A" variant="buttons" />,
      );
      expect(container).toBeEmptyDOMElement();
    }
  });
});
