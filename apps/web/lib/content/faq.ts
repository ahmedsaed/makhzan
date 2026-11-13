/**
 * The FAQ's copy (/faq), in groups. Each question's `id` is its anchor
 * (`/faq#price-differs`), so links to it must keep working: rename one only
 * with a reason, and never reuse an id for a different question.
 *
 * Claims held true elsewhere: the weekly pass (lib/content/crawling.ts); the
 * 45-day stale rule (STALE_AFTER_DAYS, lib/freshness.ts); removal within 7
 * days (lib/content/supplier-requests.ts); the 90 days a report's email is
 * kept (EMAIL_KEPT_DAYS, lib/report.ts); the report form's reasons, quoted
 * from REASONS in lib/report.ts so they cannot drift; AI training crawlers
 * refused (lib/robots.ts). tests/site-pages.test.ts holds them equal.
 *
 * Owner's decisions (November 2026): a buyer may suggest a shop to hello@;
 * makhzan's data is not offered for reuse (no API, no licence).
 */
import { HELLO_EMAIL, REPORT_LABEL } from "@/lib/content/contact";
import { plainText, type Rich } from "@/lib/content/prose";
import { STALE_AFTER_DAYS } from "@/lib/freshness";
import { EMAIL_KEPT_DAYS, REASONS, type ReasonKey } from "@/lib/report";
import { routes } from "@/lib/routes";

export type FaqItem = { id: string; question: string; answer: Rich[] };
export type FaqGroup = { title: string; items: FaqItem[] };

export const faqLead: Rich = [
  "Short answers to what people ask most. Not here? See ",
  { link: "Contact", href: routes.contact() },
  ".",
];

/** A reason's title as the report form shows it. */
function reason(key: ReasonKey): string {
  return REASONS.find((r) => r.key === key)!.title;
}

export const faqGroups: FaqGroup[] = [
  {
    title: "Buying",
    items: [
      {
        id: "is-it-a-shop",
        question: "Is makhzan a shop? Can I buy here?",
        answer: [
          [
            "No. makhzan is a directory: it has no cart, takes no payment and delivers nothing. Every offer links to the shop’s own page, and you buy from the shop and deal with them directly, including for delivery, warranty and returns.",
          ],
        ],
      },
      {
        id: "price-differs",
        question: "Why is the price different on the shop’s site?",
        answer: [
          [
            "We show what the shop’s site said when we last read it, and every offer says when that was. If the shop has changed its price or stock since, the shop’s site is right. If the offer was checked recently and still does not match, tell us with ",
            { flag: REPORT_LABEL },
            " beside the product’s title.",
          ],
        ],
      },
      {
        id: "how-often",
        question: "How often are prices and stock updated?",
        answer: [
          [
            "Every listed shop is read again about once a week: a slice of its catalogue each day, so each product is rechecked roughly weekly.",
          ],
          [
            `Each offer shows when it was last checked. Products not checked in over ${STALE_AFTER_DAYS} days are hidden from results by default and marked as out of date on their page, because a shop we cannot reach goes on ageing.`,
          ],
        ],
      },
    ],
  },
  {
    title: "What you see",
    items: [
      {
        id: "listed-twice",
        question: "Why is the same product listed twice?",
        answer: [
          [
            "Shops describe the same part in different words, and we only put two shops’ listings on one page when their titles agree. When we are unsure we keep them apart, so the same thing sometimes appears twice. Use ",
            { strong: REPORT_LABEL },
            ` and choose “${reason("same_as_other")}”.`,
          ],
        ],
      },
      {
        id: "not-the-same",
        question: "Why are two different products on one page?",
        answer: [
          [
            "That is a mistake in our matching: two parts with similar names, such as a module and a bare chip, or a pack and a single unit, were treated as one. Use ",
            { strong: REPORT_LABEL },
            `, choose “${reason("offers_not_same")}” and tick the ones that differ. A person reads every report.`,
          ],
        ],
      },
      {
        id: "missing-shop",
        question: "Why isn’t the shop I buy from here?",
        answer: [
          [
            "makhzan can only list shops whose websites publish their products and prices. Tell us about one at ",
            { email: HELLO_EMAIL },
            ". If it is your shop, use ",
            { link: "For suppliers", href: routes.forSuppliers() },
            ".",
          ],
        ],
      },
    ],
  },
  {
    title: "Shops",
    items: [
      {
        id: "shop-listed-removed",
        question: "I run a shop. How do I get listed, corrected or removed?",
        answer: [
          [
            "Everything is on ",
            { link: "For suppliers", href: routes.forSuppliers() },
            ". Removal takes at most 7 days, no questions asked, and we stop reading your site. You can also block our crawler in your robots.txt; ",
            { link: "How we crawl", href: routes.howWeCrawl() },
            " shows the two lines.",
          ],
        ],
      },
    ],
  },
  {
    title: "makhzan",
    items: [
      {
        id: "free",
        question: "Is makhzan free? Who pays for it?",
        answer: [
          [
            "makhzan is free, shows no ads, and no shop pays to be listed or to rank higher. It is made and run by Merope.",
          ],
        ],
      },
      {
        id: "my-data",
        question: "Do you sell my data?",
        answer: [
          [
            `No. There are no accounts and no cookies of ours, and we do not sell, rent or share what you send us. If you give an email with a report, it is used only to reply and deleted after ${EMAIL_KEPT_DAYS} days. The details are on `,
            { link: "Privacy", href: routes.privacy() },
            ".",
          ],
        ],
      },
      {
        id: "use-data",
        question: "Can I use makhzan’s data?",
        answer: [
          [
            "The product titles, photos, descriptions and prices belong to the shops that publish them, so makhzan offers no API or data licence. Search engines are welcome; automated copying beyond what our robots.txt allows is not, and AI training crawlers are refused. If you have something specific in mind, write to ",
            { email: HELLO_EMAIL },
            ".",
          ],
        ],
      },
      {
        id: "contact-us",
        question: "How do I contact makhzan?",
        answer: [
          [
            { link: "Contact", href: routes.contact() },
            " says which way reaches us fastest for what you need.",
          ],
        ],
      },
    ],
  },
];

/**
 * schema.org FAQPage for the page (`url` its absolute address): every
 * question with its answer as plain text, exactly as the page shows them, as
 * Google's FAQ guidance requires
 * (developers.google.com/search/docs/appearance/structured-data/faqpage).
 */
export function faqJsonLd(groups: FaqGroup[], url: string) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    url,
    mainEntity: groups.flatMap((group) =>
      group.items.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: {
          "@type": "Answer",
          text: item.answer.map(plainText).join("\n\n"),
        },
      })),
    ),
  };
}
