/**
 * The contact page's copy (/contact): which way reaches us for what. There is
 * no form and no endpoint; every route is a link or a `mailto:`.
 *
 * Two addresses, on purpose: crawler@ (CONTACT_EMAIL, lib/content/crawling.ts)
 * is for shops and for personal-data requests, as /how-we-crawl, /for-suppliers
 * and /privacy already say; hello@ is Merope's general address, for
 * everything else (the owner's choice, November 2026).
 */
import { CONTACT_EMAIL } from "@/lib/content/crawling";
import type { Rich } from "@/lib/content/prose";
import { routes } from "@/lib/routes";

/** Merope's general address: ideas, a shop to add, press, other questions. */
export const HELLO_EMAIL = "hello@merope.dev";

/** The label of the button beside each product's title (components/report-problem.tsx). */
export const REPORT_LABEL = "Report a problem";

export type ContactRoute = {
  id: string;
  title: string;
  body: Rich;
  /** The way there, when there is one to press; the report route has none. */
  action?:
    | { kind: "link"; label: string; href: string; primary?: boolean }
    | { kind: "email"; label: string; email: string };
};

export const contactLead =
  "makhzan has no contact form. Pick what fits, and it reaches the right place.";

export const contactRoutes: ContactRoute[] = [
  {
    id: "wrong",
    title: "A price, stock or product is wrong",
    body: [
      "Use ",
      { flag: REPORT_LABEL },
      " beside the product’s title. It sends us the product and the offers as you saw them, so we can fix it. To buy, or about an order, contact the shop: its details are on the product and shop pages.",
    ],
  },
  {
    id: "shops",
    title: "You run a shop",
    body: [
      "Remove your shop, add it, correct its details, or ask about how our crawler reads your site.",
    ],
    action: { kind: "link", label: "For suppliers", href: routes.forSuppliers(), primary: true },
  },
  {
    id: "data",
    title: "Your personal data",
    body: [
      "To ask what we hold about you, or to correct or delete it, write to ",
      { mono: CONTACT_EMAIL },
      ", as ",
      { link: "Privacy", href: routes.privacy() },
      " explains. Include your report’s reference (like R-1234) or the email you gave.",
    ],
    action: { kind: "email", label: "Email", email: CONTACT_EMAIL },
  },
  {
    id: "else",
    title: "Anything else",
    body: [
      "Ideas, a shop we should know about, press, or a question this site doesn’t answer: ",
      { mono: HELLO_EMAIL },
      ".",
    ],
    action: { kind: "email", label: "Email", email: HELLO_EMAIL },
  },
];

export const contactFooter: Rich = [
  "Many questions are answered in the ",
  { link: "FAQ", href: routes.faq() },
  ".",
];
