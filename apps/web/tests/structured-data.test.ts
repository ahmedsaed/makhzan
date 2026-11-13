import { describe, expect, it } from "vitest";

import type { ShopContact, SupplierProfile } from "@/lib/api";
import { openingHoursSpecification, shopJsonLd } from "@/lib/structured-data";

// Made-up shops only: the repository names real suppliers by role, never by
// name or contact details.
const S = "https://schema.org/";
const PAGE = "https://makhzan.test/shops/shop-a";
const day = (name: string) => `${S}${name}`;
const CLOSED = { opens: "00:00", closes: "00:00" };

function contact(extra: Partial<ShopContact> = {}): ShopContact {
  return {
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
    ...extra,
  };
}

function shop(extra: Partial<SupplierProfile> = {}): SupplierProfile {
  return {
    slug: "shop-a",
    name: "Shop A",
    name_ar: "متجر أ",
    website_url: "https://shop-a.example.test",
    listing_count: 120,
    in_stock_count: 84,
    last_verified_at: null,
    domains: [],
    area: null,
    governorate: null,
    contact: null,
    top_categories: [],
    ...extra,
  };
}

/** The shop node of a shop page's graph. */
function node(data: ReturnType<typeof shopJsonLd>) {
  return data["@graph"][1] as Record<string, unknown>;
}

describe("openingHoursSpecification", () => {
  it("reads the crawler's schema.org lines", () => {
    expect(openingHoursSpecification(["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"])).toEqual([
      {
        "@type": "OpeningHoursSpecification",
        dayOfWeek: ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"].map(day),
        opens: "10:00",
        closes: "20:30",
      },
      {
        "@type": "OpeningHoursSpecification",
        dayOfWeek: [day("Friday")],
        opens: "14:00",
        closes: "20:00",
      },
    ]);
  });

  it("reads hand-written lines, with a named closed day as 00:00–00:00", () => {
    expect(
      openingHoursSpecification(["Monday to Saturday 10:00 to 20:00", "Sunday closed"]),
    ).toEqual([
      {
        "@type": "OpeningHoursSpecification",
        dayOfWeek: ["Saturday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"].map(day),
        opens: "10:00",
        closes: "20:00",
      },
      { "@type": "OpeningHoursSpecification", dayOfWeek: [day("Sunday")], ...CLOSED },
    ]);
  });

  // The page reads a day no line names as closed (lib/hours.ts), and says so.
  it("states a day no line names as closed", () => {
    const week = openingHoursSpecification(["Mo-Fr 09:00-17:00"]);
    expect(week[1]).toEqual({
      "@type": "OpeningHoursSpecification",
      dayOfWeek: [day("Saturday"), day("Sunday")],
      ...CLOSED,
    });
  });

  it("reads 'Daily', and leaves holidays out of the weekly hours", () => {
    const daily = openingHoursSpecification(["Daily 10:00 to 20:00"]);
    expect(daily).toHaveLength(1);
    expect(daily[0].dayOfWeek).toHaveLength(7);
    const week = openingHoursSpecification([
      "Saturday to Thursday 10:00 to 19:00",
      "Friday and public holidays closed",
    ]);
    expect(week).toHaveLength(2);
    expect(week[1]).toEqual({
      "@type": "OpeningHoursSpecification",
      dayOfWeek: [day("Friday")],
      ...CLOSED,
    });
  });

  it("keeps a split shift as two entries for the day", () => {
    const split = openingHoursSpecification(["Mo-Fr 09:00-13:00", "Mo-Fr 15:00-19:00"]);
    expect(split.map((s) => [s.opens, s.closes])).toEqual([
      ["09:00", "13:00"],
      ["15:00", "19:00"],
      ["00:00", "00:00"],
    ]);
  });

  it("is open all day as 00:00–23:59, and closes at 24:00 as 23:59", () => {
    expect(openingHoursSpecification(["Mo-Su 00:00-23:59"])[0]).toMatchObject({
      opens: "00:00",
      closes: "23:59",
    });
    expect(openingHoursSpecification(["Mo-Su 10:00-24:00"])[0]).toMatchObject({
      opens: "10:00",
      closes: "23:59",
    });
  });

  // schema.org reads days alone as open all day; a person has not said that.
  it("reads days without times as all day only in the crawler's schema.org data", () => {
    expect(openingHoursSpecification(["Monday to Saturday"])).toEqual([]);
    expect(openingHoursSpecification(["Mo-Su"])).toEqual([]);
    expect(openingHoursSpecification(["Mo-Su"], { crawled: true })[0]).toMatchObject({
      opens: "00:00",
      closes: "23:59",
    });
  });

  // One line read without the others would misstate the week.
  it("marks up nothing when any line does not parse", () => {
    expect(
      openingHoursSpecification(["Monday to Saturday 10:00 to 20:00", "Ring before visiting"]),
    ).toEqual([]);
    expect(openingHoursSpecification([])).toEqual([]);
  });
});

describe("shopJsonLd", () => {
  it("is a directory page about the shop; the shop's url is its own site", () => {
    const data = shopJsonLd(shop(), PAGE);
    expect(data["@context"]).toBe("https://schema.org");
    expect(data["@graph"][0]).toEqual({
      "@type": "WebPage",
      "@id": PAGE,
      url: PAGE,
      name: "Shop A",
      about: { "@id": `${PAGE}#shop` },
      mainEntity: { "@id": `${PAGE}#shop` },
      isPartOf: { "@id": "https://makhzan.test/#website" },
    });
    expect(node(data)).toEqual({
      "@type": "OnlineStore",
      "@id": `${PAGE}#shop`,
      name: "Shop A",
      url: "https://shop-a.example.test",
    });
  });

  it("is a Store with a street address: address, phone, email, hours and map", () => {
    const data = shopJsonLd(
      shop({
        contact: contact({
          phones: ["+201000000001", "+20200000002"],
          email: "sales@shop-a.example.test",
          address: "12 Example Street, 2nd floor",
          area: "Example District",
          governorate: "Cairo",
          maps_url: "https://maps.example.test/shop-a",
          opening_hours: ["Monday to Saturday 10:00 to 20:00", "Sunday closed"],
        }),
      }),
      PAGE,
    );
    expect(node(data)).toMatchObject({
      "@type": "Store",
      url: "https://shop-a.example.test",
      address: {
        "@type": "PostalAddress",
        // Cairo is the city: the district joins the street.
        streetAddress: "12 Example Street, 2nd floor, Example District",
        addressLocality: "Cairo",
        addressRegion: "Cairo",
        addressCountry: "EG",
      },
      telephone: "+201000000001",
      email: "sales@shop-a.example.test",
      hasMap: "https://maps.example.test/shop-a",
    });
    expect(node(data).openingHoursSpecification).toHaveLength(2);
    expect(node(data)).not.toHaveProperty("alternateName");
    expect(node(data)).not.toHaveProperty("sameAs");
  });

  it("uses the area as the town outside the city governorates", () => {
    const store = node(
      shopJsonLd(
        shop({
          contact: contact({
            address: "3 Market Road",
            area: "Example Town",
            governorate: "Sharqia",
          }),
        }),
        PAGE,
      ),
    );
    expect(store.address).toEqual({
      "@type": "PostalAddress",
      streetAddress: "3 Market Road",
      addressLocality: "Example Town",
      addressRegion: "Sharqia",
      addressCountry: "EG",
    });
  });

  it("claims nothing it does not have", () => {
    const data = shopJsonLd(shop({ website_url: null, contact: contact() }), PAGE);
    expect(node(data)).toEqual({ "@type": "Organization", "@id": `${PAGE}#shop`, name: "Shop A" });
  });

  // Hours and a map belong to a place; without a street address it is not one.
  it("without a street address: an OnlineStore with its region, no hours or map", () => {
    const online = node(
      shopJsonLd(
        shop({
          contact: contact({
            governorate: "Alexandria",
            phones: ["+201000000003"],
            maps_url: "https://maps.example.test/x",
            opening_hours: ["Daily 10:00 to 20:00"],
          }),
        }),
        PAGE,
      ),
    );
    expect(online).toMatchObject({
      "@type": "OnlineStore",
      address: {
        "@type": "PostalAddress",
        addressLocality: "Alexandria",
        addressRegion: "Alexandria",
      },
      telephone: "+201000000003",
    });
    expect(online).not.toHaveProperty("openingHoursSpecification");
    expect(online).not.toHaveProperty("hasMap");
  });

  it("leaves out hours it cannot read", () => {
    const store = node(
      shopJsonLd(
        shop({ contact: contact({ address: "1 Street", opening_hours: ["By appointment"] }) }),
        PAGE,
      ),
    );
    expect(store).not.toHaveProperty("openingHoursSpecification");
  });

  it("reads days-only hours as all day when the crawler read them from the shop's markup", () => {
    const hours = (crawled: boolean) =>
      node(
        shopJsonLd(
          shop({
            contact: contact({
              address: "1 Street",
              opening_hours: ["Mo-Su"],
              sources: [
                {
                  origin: crawled ? "read" : "listed",
                  url: "https://shop-a.example.test/",
                  checked_on: "2026-11-01",
                  fields: ["opening_hours"],
                },
              ],
            }),
          }),
          PAGE,
        ),
      ).openingHoursSpecification;
    expect(hours(true)).toHaveLength(1);
    expect(hours(false)).toBeUndefined();
  });

  it("lists branches with a street address as Stores of their own", () => {
    const store = node(
      shopJsonLd(
        shop({
          contact: contact({
            address: "12 Example Street",
            branches: [
              {
                name: "North branch",
                address: "7 Branch Street",
                area: "Example Town",
                governorate: "Sharqia",
                phones: ["+20500000004"],
                maps_url: null,
              },
              {
                name: "Pickup point",
                address: null,
                area: "Example District",
                governorate: "Giza",
                phones: ["+201000000005"],
                maps_url: null,
              },
            ],
          }),
        }),
        PAGE,
      ),
    );
    expect(store.subOrganization).toEqual([
      {
        "@type": "Store",
        name: "North branch",
        address: {
          "@type": "PostalAddress",
          streetAddress: "7 Branch Street",
          addressLocality: "Example Town",
          addressRegion: "Sharqia",
          addressCountry: "EG",
        },
        telephone: "+20500000004",
      },
    ]);
  });
});
