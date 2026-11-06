import { CONTACT_EMAIL } from "@/lib/content/crawling";

/**
 * The three things a shop owner can ask of makhzan, as prefilled emails.
 *
 * Mail rather than a form: requests are handled by hand for now
 * (docs/PRODUCT.md), a form would need a backend to receive it, and an email
 * leaves the owner holding a copy of what they asked and when. The body is a
 * template to fill in, so a request arrives with what is needed to act on it.
 */

export type SupplierRequest = {
  id: "remove" | "add" | "correct" | "schedule";
  title: string;
  /** What happens, in one or two sentences. */
  summary: string;
  action: string;
  subject: string;
  body: string;
};

/**
 * `mailto:` with a subject and body. Encoded with encodeURIComponent, not
 * URLSearchParams: the latter writes spaces as `+`, which mail clients show
 * literally ("Remove+my+shop").
 */
export function mailtoHref(
  to: string,
  { subject, body }: { subject: string; body?: string },
): string {
  const parts = [`subject=${encodeURIComponent(subject)}`];
  if (body) parts.push(`body=${encodeURIComponent(body)}`);
  return `mailto:${to}?${parts.join("&")}`;
}

export const supplierRequests: SupplierRequest[] = [
  {
    id: "remove",
    title: "Remove my shop",
    summary:
      "Your shop and every product from it are taken off makhzan within 7 days, and we stop reading your site. No questions asked.",
    action: "Ask to be removed",
    subject: "Remove my shop from makhzan",
    body: [
      "Please remove my shop from makhzan.",
      "",
      "Shop name:",
      "Shop website:",
      "",
      "(Optional) Anything you would like us to know:",
    ].join("\n"),
  },
  {
    id: "add",
    title: "Add my shop",
    summary:
      "Sell hardware or electronics in Egypt and have a website with prices? We can list it, at no cost.",
    action: "Ask to be listed",
    subject: "Add my shop to makhzan",
    body: [
      "Please add my shop to makhzan.",
      "",
      "Shop name:",
      "Shop website:",
      "What we sell:",
      "Address (area, governorate):",
      "Phone or WhatsApp:",
      "Opening hours:",
    ].join("\n"),
  },
  {
    id: "correct",
    title: "Correct my details",
    summary:
      "Add or fix your location, phone, WhatsApp or opening hours, or tell us about wrong prices or categories.",
    action: "Send a correction",
    subject: "Correct my shop's details on makhzan",
    body: [
      "Please correct my shop's details on makhzan.",
      "",
      "Shop name:",
      "Shop website:",
      "",
      "Location (area, governorate):",
      "Phone:",
      "WhatsApp:",
      "Opening hours:",
      "",
      "Wrong prices or categories (links to the products, and what is wrong):",
    ].join("\n"),
  },
  {
    id: "schedule",
    title: "Change when or how fast we crawl",
    summary:
      "By default we read your site early in the morning, Egypt time, one page every 15 seconds or slower. Ask for another hour, a slower pace, or fewer pages a day.",
    action: "Ask for a different schedule",
    subject: "Change how makhzan crawls my shop",
    body: [
      "Please change how makhzan crawls my shop.",
      "",
      "Shop name:",
      "Shop website:",
      "",
      "Preferred hours (Egypt time):",
      "Slowest pace you would like (seconds between requests):",
      "Most pages per day:",
    ].join("\n"),
  },
];

export { CONTACT_EMAIL };
