import type { ContactSource, ShopContact, ShopReach } from "@/lib/api";
import { CONTACT_EMAIL, mailtoHref } from "@/lib/content/supplier-requests";
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

/** Egyptian five-digit hotlines: 15xxx, 16xxx, 17xxx, 19xxx (as contact.py). */
const HOTLINE = /^1[5679]\d{3}$/;

/** "010 0123 4567", "02 2345 6789", "03 123 4567", "040 123 4567", "19123". */
export function formatPhone(number: string): string {
  if (HOTLINE.test(number)) return number;
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
    // Every other area, 013 (Banha) and 015 (10th of Ramadan) among them.
    return `${national.slice(0, 3)} ${national.slice(3, 6)} ${national.slice(6)}`;
  }
  return national;
}

/** `tel:+20…` (or `tel:19123`), or null for a number we cannot dial. */
export function telHref(number: string): string | null {
  return /^\+\d{8,15}$/.test(number) || HOTLINE.test(number) ? `tel:${number}` : null;
}

/** `https://wa.me/201001234567`: WhatsApp's own click-to-chat link, digits only. */
export function whatsappHref(number: string): string | null {
  return /^\+\d{8,15}$/.test(number) ? `https://wa.me/${number.slice(1)}` : null;
}

/** `mailto:` for a shop's own address. */
export function emailHref(email: string): string {
  return `mailto:${email}`;
}

/**
 * "Something wrong? Tell us": an email to makhzan, its subject naming the shop
 * (and the product, on a product page), its body asking what is wrong and
 * carrying the page, so a report arrives with what is needed to act on it.
 */
export function reportHref({
  shop,
  product,
  page,
}: {
  shop: string;
  product?: string;
  page: string;
}): string {
  return mailtoHref(CONTACT_EMAIL, {
    subject: product ? `Something wrong: ${product} at ${shop}` : `Something wrong: ${shop}`,
    body: [
      "What is wrong, and what should it say?",
      "",
      "",
      "",
      "---",
      `Shop: ${shop}`,
      ...(product ? [`Product: ${product}`] : []),
      `Page: ${page}`,
    ].join("\n"),
  });
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
  const verb = missing.length === 1 && missing[0] !== "opening hours" ? "isn't" : "aren't";
  return `${capitalize(inWords(missing))} ${verb} listed yet.`;
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

/** "Shop A's", "Nile Parts'". */
export function possessive(name: string): string {
  return /s$/i.test(name) ? `${name}'` : `${name}'s`;
}

/** Second-level domains under which a registrable domain has three labels. */
const SECOND_LEVEL = new Set(["com", "net", "org", "edu", "gov", "co", "ac"]);

/**
 * The domain a business registers: "nile-parts.com" for
 * store.nile-parts.com, "shop.com.eg" for www.shop.com.eg. Approximate
 * (no public-suffix list), which is enough to tell a shop's own pages apart.
 */
export function registrableDomain(host: string): string {
  const labels = host.toLowerCase().replace(/\.$/, "").split(".");
  const take =
    labels.length >= 3 &&
    labels[labels.length - 1].length === 2 &&
    SECOND_LEVEL.has(labels[labels.length - 2])
      ? 3
      : 2;
  return labels.slice(-take).join(".");
}

/**
 * What a source page is, in words a buyer trusts the right amount: "Nile Parts'
 * website" for a page on the shop's own domain (either may be a subdomain of
 * the other); "Google Maps", "Facebook", "Instagram" for those, never "the
 * shop's" (a Google Maps listing is often not the shop's own, and its page
 * on a social network may not be either); the host for anything else.
 */
export function sourceLabel(url: string, shopName: string, websiteUrl: string | null): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }
  const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
  const path = parsed.pathname;
  if (
    (/^google\.[a-z.]+$/.test(host) && path.startsWith("/maps")) ||
    /^maps\.google\.[a-z.]+$/.test(host) ||
    host === "maps.app.goo.gl" ||
    (host === "goo.gl" && path.startsWith("/maps")) ||
    host === "g.page"
  ) {
    return "Google Maps";
  }
  if (host === "maps.apple.com") return "Apple Maps";
  if (/(^|\.)(facebook\.com|fb\.com)$/.test(host)) return "Facebook";
  if (/(^|\.)instagram\.com$/.test(host)) return "Instagram";
  if (websiteUrl) {
    const site = hostOf(websiteUrl);
    if (registrableDomain(site) === registrableDomain(host))
      return `${possessive(shopName)} website`;
  }
  return host;
}

/** How a contact field is named in a sentence about where it came from. */
const FIELD_WORDS: Record<string, string> = {
  phones: "phone",
  whatsapp: "WhatsApp",
  email: "email",
  address: "address",
  area: "address",
  governorate: "address",
  maps_url: "map link",
  opening_hours: "opening hours",
  branches: "branches",
};

function inWords(items: string[]): string {
  return items.length <= 1
    ? (items[0] ?? "")
    : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function capitalize(text: string): string {
  return text ? `${text[0].toUpperCase()}${text.slice(1)}` : text;
}

type Entry = { verb: string; when: string | null; fields: string[] };

function verbOf(source: ContactSource): string {
  return source.origin === "read" ? "read automatically" : "checked";
}

function when(entry: Entry): string {
  return entry.when ? `${entry.verb} ${entry.when}` : entry.verb;
}

/**
 * Where the details came from, in one sentence, grouped by place:
 *
 *   "From Shop A's website, checked 3 Nov 2026."
 *   "Phone, WhatsApp and email from Nile Parts' website and address from Google
 *    Maps, all checked 10 Nov 2026."
 *   "Phone, email and address from Shop A's website, checked 3 Nov 2026, and
 *    WhatsApp and opening hours read automatically 8 Nov 2026."
 *
 * "checked" is a person reading the page; "read automatically" the crawler
 * reading the shop's structured data. Null when no source says where or when.
 */
export function provenance(
  contact: ShopContact,
  shopName: string,
  websiteUrl: string | null,
): string | null {
  const groups = new Map<string, Entry[]>();
  for (const source of contact.sources) {
    const label = source.url ? sourceLabel(source.url, shopName, websiteUrl) : null;
    const day = formatCheckedOn(source.checked_on);
    if (!label && !day) continue;
    const key = label ?? "";
    const entries = groups.get(key) ?? [];
    const words = source.fields.map((f) => FIELD_WORDS[f] ?? f);
    const same = entries.find((e) => e.verb === verbOf(source) && e.when === day);
    if (same) same.fields.push(...words);
    else entries.push({ verb: verbOf(source), when: day, fields: words });
    groups.set(key, entries);
  }
  for (const entries of groups.values()) {
    for (const entry of entries) entry.fields = [...new Set(entry.fields)];
  }
  const all = [...groups.entries()];
  if (all.length === 0) return null;
  const from = (label: string) => (label ? ` from ${label}` : "");

  if (all.length === 1 && all[0][1].length === 1) {
    const [label, [entry]] = all[0];
    return label ? `From ${label}, ${when(entry)}.` : `${capitalize(when(entry))}.`;
  }
  const entries = all.flatMap(([, list]) => list);
  const shared = entries.every((e) => e.verb === entries[0].verb && e.when === entries[0].when);
  if (shared) {
    const phrases = all.map(([label, [entry]]) => `${inWords(entry.fields)}${from(label)}`);
    return `${capitalize(inWords(phrases))}, all ${when(entries[0])}.`;
  }
  const phrases = all.map(([label, list]) =>
    list
      .map((entry, index) =>
        index === 0
          ? `${inWords(entry.fields)}${from(label)}, ${when(entry)}`
          : `${inWords(entry.fields)} ${when(entry)}`,
      )
      .join(", and "),
  );
  return `${capitalize(phrases.join("; "))}.`;
}

/** Whether an offer's shop can be reached from the product page at all. */
export function isReachable(reach: ShopReach | null | undefined): reach is ShopReach {
  return Boolean(reach && (reach.phone || reach.whatsapp || reach.email));
}
