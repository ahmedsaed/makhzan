import type { ShopContact, ShopReach } from "@/lib/api";
import { hostOf } from "@/lib/shops";

/**
 * A shop's contact details as text and links: numbers formatted for an
 * Egyptian reader ("010 0123 4567", "02 2345 6789") but linked in E.164
 * (`tel:+201001234567`, `https://wa.me/201001234567`), which works from any
 * phone, in Egypt or not.
 *
 * The API serves numbers already normalized (makhzan_schemas/contact.py): E.164,
 * or a five-digit hotline. Anything else is shown as it came and not linked.
 */

/** "010 0123 4567", "02 2345 6789", "03 123 4567", "040 123 4567", "19123". */
export function formatPhone(number: string): string {
  if (/^1\d{4}$/.test(number)) return number;
  const match = /^\+20(\d{8,10})$/.exec(number);
  if (!match) return number;
  const national = `0${match[1]}`;
  if (national.length === 11) {
    // Mobile: 01x xxxx xxxx.
    return `${national.slice(0, 3)} ${national.slice(3, 7)} ${national.slice(7)}`;
  }
  if (national.startsWith("02") && national.length === 10) {
    return `02 ${national.slice(2, 6)} ${national.slice(6)}`;
  }
  if (national.startsWith("03") && national.length === 9) {
    return `03 ${national.slice(2, 5)} ${national.slice(5)}`;
  }
  if (national.length === 10) {
    return `${national.slice(0, 3)} ${national.slice(3, 6)} ${national.slice(6)}`;
  }
  return national;
}

/** `tel:+20…` (or `tel:19123`), or null for a number we cannot dial. */
export function telHref(number: string): string | null {
  return /^\+\d{8,15}$/.test(number) || /^1\d{4}$/.test(number) ? `tel:${number}` : null;
}

/** `https://wa.me/201001234567`: WhatsApp's own click-to-chat link, digits only. */
export function whatsappHref(number: string): string | null {
  return /^\+\d{8,15}$/.test(number) ? `https://wa.me/${number.slice(1)}` : null;
}

export function mailtoHref(email: string): string {
  return `mailto:${email}`;
}

/** What a shop page can still not say about how to reach the shop. */
export type MissingDetail = "address" | "phone" | "opening hours";

/**
 * The details a buyer looks for that nobody has found yet, in the order they
 * are named. A phone is had through WhatsApp too, and a branch's address or
 * number counts: the buyer can reach the shop either way.
 */
export function missingDetails(contact: ShopContact | null | undefined): MissingDetail[] {
  const branches = contact?.branches ?? [];
  const missing: MissingDetail[] = [];
  if (!contact?.address && !branches.some((b) => b.address)) missing.push("address");
  if (!contact?.phones.length && !contact?.whatsapp && !branches.some((b) => b.phones.length)) {
    missing.push("phone");
  }
  if (!contact?.opening_hours.length) missing.push("opening hours");
  return missing;
}

/** "Address, phone and opening hours aren't listed yet." — or null when none is missing. */
export function missingLine(contact: ShopContact | null | undefined): string | null {
  const missing = missingDetails(contact);
  if (missing.length === 0) return null;
  const words =
    missing.length === 1
      ? missing[0]
      : `${missing.slice(0, -1).join(", ")} and ${missing[missing.length - 1]}`;
  const verb = missing.length === 1 && missing[0] !== "opening hours" ? "isn't" : "aren't";
  return `${words[0].toUpperCase()}${words.slice(1)} ${verb} listed yet.`;
}

const DAY = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** "12 Nov 2026" for an ISO day ("2026-11-12"), or null. */
export function formatCheckedOn(day: string | null): string | null {
  if (!day || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const date = new Date(`${day}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : DAY.format(date);
}

/** How a contact field is named in a sentence about where it came from. */
const FIELD_WORDS: Record<string, string> = {
  phones: "phone",
  whatsapp: "WhatsApp",
  email: "email",
  address: "address",
  area: "area",
  governorate: "area",
  maps_url: "map link",
  opening_hours: "opening hours",
  branches: "branches",
};

function inWords(items: string[]): string {
  return items.length <= 1
    ? (items[0] ?? "")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * Where the details came from, one sentence a source: "From Shop A's website,
 * checked 3 Nov 2026." The website by name when the page is on the shop's own
 * site, its host otherwise (a shop's Facebook page). What the crawler read,
 * beside what a person listed, names its fields: "WhatsApp and opening hours
 * read automatically from Shop A's website, 8 Nov 2026." A source that says
 * neither where nor when is not mentioned: there is nothing to say.
 */
export function sourceLines(
  contact: ShopContact,
  shopName: string,
  websiteUrl: string | null,
): string[] {
  const site = websiteUrl ? hostOf(websiteUrl) : null;
  const both = contact.sources.length > 1;
  return contact.sources.flatMap((source) => {
    const host = source.url ? hostOf(source.url) : null;
    const where = host
      ? host === site || (site !== null && host.endsWith(`.${site}`))
        ? `${shopName}'s website`
        : host
      : null;
    const when = formatCheckedOn(source.checked_on);
    if (!where && !when) return [];
    if (source.origin === "read" && both && where) {
      const fields = inWords([...new Set(source.fields.map((f) => FIELD_WORDS[f] ?? f))]);
      const subject = fields ? `${fields[0].toUpperCase()}${fields.slice(1)}` : "Some details";
      return [`${subject} read automatically from ${where}${when ? `, ${when}` : ""}.`];
    }
    const verb = source.origin === "read" ? "read automatically" : "checked";
    if (where && when) return [`From ${where}, ${verb} ${when}.`];
    if (where) return [`From ${where}.`];
    return [`Checked ${when}.`];
  });
}

/** Whether an offer's shop can be reached from the product page at all. */
export function isReachable(reach: ShopReach | null | undefined): reach is ShopReach {
  return Boolean(reach && (reach.phone || reach.whatsapp || reach.email));
}
