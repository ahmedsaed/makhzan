/**
 * The terms of use (/terms), short and written to be read.
 *
 * Not reviewed by a lawyer when it was published (13 November 2026). The
 * owner may want one to read it, in particular "Our liability" (Egypt's
 * Consumer Protection Law, Law No. 181 of 2018) and "Governing law".
 *
 * Its facts are the site's: the weekly pass (lib/content/crawling.ts), photos
 * loading from the shops' sites (decision 0003, /privacy), correction and
 * removal on /for-suppliers. Change them together.
 */
import { HELLO_EMAIL } from "@/lib/content/contact";
import type { Rich } from "@/lib/content/prose";
import { routes } from "@/lib/routes";

export const TERMS_UPDATED = "13 November 2026";

export type TermsBlock = { kind: "p"; text: Rich } | { kind: "list"; items: Rich[] };

export type TermsSection = { id: string; title: string; blocks: TermsBlock[] };

const p = (...text: Rich): TermsBlock => ({ kind: "p", text });

export const termsLead: Rich = [
  "These terms apply when you use makhzan at makhzan.merope.dev. They are short, and written to be read. By using makhzan you agree to them; if you do not, please do not use it. “We” means Merope, who makes and runs makhzan.",
];

export const termsSections: TermsSection[] = [
  {
    id: "what",
    title: "What makhzan is",
    blocks: [
      p(
        "makhzan is a free directory of Egyptian hardware and electronics shops. It shows products from the shops’ public websites and links to each shop’s own page. makhzan sells nothing, takes no orders or payments, and delivers nothing.",
      ),
    ],
  },
  {
    id: "accuracy",
    title: "The information may be wrong or out of date",
    blocks: [
      p(
        "Prices, stock, titles, photos, specifications and contact details are read from the shops’ own sites by our crawler, about once a week, and matched across shops by software that can make mistakes. A shop can change its site at any time after we read it. Every offer shows when it was last checked; confirm on the shop’s site before you buy.",
      ),
      p(
        "makhzan is provided as it is, without any promise that it is accurate, complete, up to date, available or suitable for a particular purpose.",
      ),
    ],
  },
  {
    id: "buying",
    title: "Buying is between you and the shop",
    blocks: [
      p(
        "When you follow a link to a shop, any purchase, payment, delivery, warranty, return or dispute is between you and that shop. We are not a party to it. A shop being listed is not a recommendation, and we do not vouch for any shop.",
      ),
    ],
  },
  {
    id: "use",
    title: "Using makhzan fairly",
    blocks: [
      p("You may use makhzan to search and compare, for yourself or for your work. Please do not:"),
      {
        kind: "list",
        items: [
          [
            "crawl, scrape or copy makhzan by automated means beyond what its ",
            { link: "robots.txt", href: "/robots.txt" },
            " allows, or in a way that slows the site for others;",
          ],
          ["send false, abusive or automated reports;"],
          ["use the shops’ contact details shown here for spam, bulk marketing or harassment;"],
          [
            "try to break, overload or get around makhzan’s security, or pretend to be makhzan or Merope.",
          ],
        ],
      },
      p("We may block access that does any of these."),
    ],
  },
  {
    id: "content",
    title: "Whose content it is",
    blocks: [
      p(
        "Product titles, descriptions, photos, prices, shop names, logos and trademarks belong to the shops and their owners. Photos load from the shops’ own websites. makhzan’s name, logo, design and code belong to Merope. A shop can ask to be corrected or removed on ",
        { link: "For suppliers", href: routes.forSuppliers() },
        ".",
      ),
    ],
  },
  {
    id: "links",
    title: "Links to other sites",
    blocks: [
      p(
        "Links to shops and other sites take you off makhzan. Their own terms and privacy policies apply there, and we are not responsible for what they publish or do.",
      ),
    ],
  },
  {
    id: "liability",
    title: "Our liability",
    blocks: [
      p(
        "To the extent Egyptian law allows, we are not liable for any loss that comes from using makhzan or relying on what it shows, including a purchase from a shop, a price or stock that turned out to be wrong, or makhzan being unavailable. Nothing in these terms limits any liability that Egyptian law does not allow to be limited.",
      ),
    ],
  },
  {
    id: "privacy",
    title: "Privacy",
    blocks: [
      p(
        "What makhzan keeps about you, and for how long, is on ",
        { link: "Privacy", href: routes.privacy() },
        ".",
      ),
    ],
  },
  {
    id: "changes",
    title: "Changes",
    blocks: [
      p(
        "If we change these terms, we change this page and the date at the top. Using makhzan after that means you accept the new terms.",
      ),
    ],
  },
  {
    id: "law",
    title: "Governing law",
    blocks: [
      p(
        "These terms are governed by the laws of Egypt, and any dispute about them goes to the courts of Egypt.",
      ),
    ],
  },
  {
    id: "questions",
    title: "Questions",
    blocks: [p("Write to ", { email: HELLO_EMAIL }, ".")],
  },
];
