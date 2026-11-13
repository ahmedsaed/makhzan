/**
 * schema.org for a shop's page: the shop, inside the directory page that
 * describes it.
 *
 * A shop page is a directory listing, and is marked up as one: a `WebPage`
 * (makhzan's) whose `about` and `mainEntity` are the shop. That is the usual
 * shape for a directory, and keeps the markup from reading as makhzan
 * claiming to be the shop: the shop's own `url` is its own website, and
 * makhzan's page is only the page about it. The page's `isPartOf` is
 * makhzan's WebSite (lib/metadata.ts).
 *
 * Fields follow Google's local business guidance
 * (developers.google.com/search/docs/appearance/structured-data/local-business):
 * `name`, `address` (PostalAddress), `telephone`, `openingHoursSpecification`,
 * `url`, and only what we have. Nothing is invented: no geo coordinates (a
 * map link is not coordinates), no price range, no logo (no shop has one),
 * and a field we do not know is left out rather than filled with a guess.
 *
 * The type says what we know of the shop as a place:
 * - `Store` only with a street address: a LocalBusiness is a place a buyer
 *   can go to, and Google's local business markup requires the address.
 *   Plain `Store`, not `ElectronicsStore` or `HardwareStore`: those name
 *   retail trades (consumer electronics, building hardware) that a
 *   components dealer, a 3D-printing supplier and a multi-vertical
 *   marketplace do not fit.
 * - `OnlineStore` without one but with a website: what is known is that it
 *   sells online.
 * - `Organization` with neither.
 * Opening hours and a map are properties of a place (schema.org `Place`), so
 * only a `Store` carries them.
 */
import type { ShopBranch, ShopContact, SupplierProfile } from "@/lib/api";
import { parseOpeningHoursLine } from "@/lib/hours";
import { websiteId } from "@/lib/metadata";

const SCHEMA = "https://schema.org/";

/** schema.org's DayOfWeek, in lib/hours.ts's week order (Saturday first). */
const DAY_OF_WEEK = [
  "Saturday",
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
].map((day) => `${SCHEMA}${day}`);

/** Governorates that are a city of the same name: the city is the locality. */
const CITY_GOVERNORATES = new Set(["cairo", "giza", "alexandria"]);

export type OpeningHoursSpecification = {
  "@type": "OpeningHoursSpecification";
  dayOfWeek: string[];
  opens: string;
  closes: string;
};

/**
 * A hand-written line ("Monday to Saturday 10:00 to 20:00", "Daily 10:00 to
 * 20:00", "Friday and public holidays closed") rewritten into the schema.org
 * form lib/hours.ts already reads ("Monday-Saturday 10:00-20:00"). Only the
 * connecting words change; a line with anything else in it still fails to
 * parse. "And public holidays" is dropped from a closed line: holidays are
 * special hours, which the weekly specification cannot say, and leaving them
 * out says nothing false about the week.
 */
function normalizeLine(line: string): string {
  return line
    .trim()
    .replace(/\s+(?:and|&)\s+(?:public|official|national)\s+holidays(?=\s+(?:closed|off)$)/i, "")
    .replace(/^daily\b/i, "Mo-Su")
    .replace(/\s+to\s+/gi, "-");
}

/** Days with no hours: schema.org's "open all day", but only in schema.org data. */
function daysOnly(line: string): boolean {
  return !/\d/.test(line) && !/\b(?:closed|off)\s*$/i.test(line);
}

/** 24:00 is the end of the day; schema.org Time stops at 23:59. */
function closingTime(time: string): string {
  return time === "24:00" ? "23:59" : time;
}

/**
 * The shop's opening hours as schema.org OpeningHoursSpecification, one entry
 * per set of days with the same hours (Google's local business guidance,
 * "openingHoursSpecification"). Open all day is 00:00–23:59; a closed day,
 * named so or not named at all (schema.org's own reading, and the page's,
 * lib/hours.ts), is opens = closes = 00:00, as that guidance specifies.
 *
 * `crawled`: the lines are the shop's own schema.org markup, read by the
 * crawler. Only there does a line of days alone ("Mo-Su") mean open all day;
 * a person writing "Monday to Saturday" without times has not said that.
 *
 * All or nothing, like the page: when any line does not parse, none is
 * marked up, since one line read without the others ("Sunday closed" without
 * "Monday to Saturday …") would misstate the week.
 */
export function openingHoursSpecification(
  lines: string[],
  { crawled = false }: { crawled?: boolean } = {},
): OpeningHoursSpecification[] {
  const cleaned = lines.map((line) => normalizeLine(line)).filter(Boolean);
  if (!crawled && cleaned.some(daysOnly)) return [];
  const parsed = cleaned.map(parseOpeningHoursLine);
  if (parsed.length === 0 || parsed.some((line) => line === null)) return [];

  // Per day, its spans as [opens, closes] pairs, read as the page reads them
  // (lib/hours.ts): two open lines for one day are a split shift, and
  // otherwise a later line replaces an earlier one.
  const byDay = new Map<number, { split: boolean; spans: [string, string][] }>();
  for (const line of parsed as NonNullable<(typeof parsed)[number]>[]) {
    const split = line.hours.kind === "open";
    const spans: [string, string][] =
      line.hours.kind === "closed"
        ? [["00:00", "00:00"]]
        : line.hours.kind === "allDay"
          ? [["00:00", "23:59"]]
          : line.hours.spans.map((span) => {
              const [opens, closes] = span.split("–");
              return [opens, closingTime(closes)];
            });
    for (const day of line.days) {
      const before = byDay.get(day);
      byDay.set(day, {
        split,
        spans: before?.split && split ? [...before.spans, ...spans] : spans,
      });
    }
  }
  for (let day = 0; day < 7; day++) {
    if (!byDay.has(day)) byDay.set(day, { split: false, spans: [["00:00", "00:00"]] });
  }

  const groups = new Map<string, { days: number[]; opens: string; closes: string }>();
  for (const [day, { spans }] of [...byDay.entries()].sort(([a], [b]) => a - b)) {
    for (const [opens, closes] of spans) {
      const key = `${opens}-${closes}`;
      const group = groups.get(key) ?? { days: [], opens, closes };
      group.days.push(day);
      groups.set(key, group);
    }
  }
  // Open hours first, the closed days last, as the page lists them.
  const closed = (group: { opens: string; closes: string }) =>
    Number(group.opens === "00:00" && group.closes === "00:00");
  const ordered = [...groups.values()].sort((a, b) => closed(a) - closed(b));
  return ordered.map(({ days, opens, closes }) => ({
    "@type": "OpeningHoursSpecification",
    dayOfWeek: days.map((day) => DAY_OF_WEEK[day]),
    opens,
    closes,
  }));
}

/**
 * A PostalAddress from what we have, in Egypt; null with nothing to say.
 * Where the governorate is a city (Cairo, Giza, Alexandria) the city is the
 * locality and the area, a district of it, joins the street address; in any
 * other governorate the area is the town, and is the locality.
 */
function postalAddress(
  street: string | null,
  area: string | null,
  governorate: string | null,
): Record<string, string> | null {
  if (!street && !area && !governorate) return null;
  const city = governorate && CITY_GOVERNORATES.has(governorate.trim().toLowerCase());
  const streetLine = city
    ? [street, area && !street?.includes(area) ? area : null].filter(Boolean).join(", ")
    : street;
  const locality = city ? governorate : area;
  return {
    "@type": "PostalAddress",
    ...(streetLine && { streetAddress: streetLine }),
    ...(locality && { addressLocality: locality }),
    ...(governorate && { addressRegion: governorate }),
    addressCountry: "EG",
  };
}

/** A branch with a street address as a Store of its own; null without one. */
function branchJsonLd(branch: ShopBranch, shopName: string): object | null {
  if (!branch.address) return null;
  return {
    "@type": "Store",
    name: branch.name || shopName,
    address: postalAddress(branch.address, branch.area, branch.governorate),
    ...(branch.phones[0] && { telephone: branch.phones[0] }),
    ...(branch.maps_url && { hasMap: branch.maps_url }),
  };
}

/**
 * The shop page's structured data: a `@graph` of the directory page (`page`,
 * makhzan's absolute URL) and the shop it is about. Contact details are the
 * resolved ones (`contact`, makhzan_schemas.contact.resolve_contact), the
 * same the page shows.
 */
export function shopJsonLd(supplier: SupplierProfile, page: string) {
  const contact: ShopContact | null = supplier.contact ?? null;
  const shopId = `${page}#shop`;
  const street = contact?.address ?? null;
  const type = street ? "Store" : supplier.website_url ? "OnlineStore" : "Organization";
  const address = postalAddress(
    street,
    contact?.area ?? supplier.area,
    contact?.governorate ?? supplier.governorate,
  );
  const phone = contact?.phones[0];
  const crawled = (contact?.sources ?? []).some(
    (source) => source.origin === "read" && source.fields.includes("opening_hours"),
  );
  const hours =
    type === "Store" ? openingHoursSpecification(contact?.opening_hours ?? [], { crawled }) : [];
  const branches = (contact?.branches ?? [])
    .map((branch) => branchJsonLd(branch, supplier.name))
    .filter((branch): branch is object => branch !== null);
  return {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "WebPage",
        "@id": page,
        url: page,
        name: supplier.name,
        about: { "@id": shopId },
        mainEntity: { "@id": shopId },
        isPartOf: { "@id": websiteId(page) },
      },
      {
        "@type": type,
        "@id": shopId,
        name: supplier.name,
        ...(supplier.website_url && { url: supplier.website_url }),
        ...(address && { address }),
        ...(phone && { telephone: phone }),
        ...(contact?.email && { email: contact.email }),
        ...(hours.length > 0 && { openingHoursSpecification: hours }),
        ...(type === "Store" && contact?.maps_url && { hasMap: contact.maps_url }),
        ...(branches.length > 0 && { subOrganization: branches }),
      },
    ],
  };
}
