/**
 * The privacy page's copy (/privacy), kept as prose apart from its markup, like
 * the crawling page's.
 *
 * It must stay true. Each figure here is enforced in code or in operations:
 * the 90 days and 24 hours by the worker's purge, every 10 minutes
 * (`makhzan_schemas/reports.py`); the scrambled address by the API
 * (`apps/api/app/routers/reports.py`); "no cookie" by there being none of
 * ours; the 30-day access log by the web server's log rotation on the
 * production host (docs/DEPLOYMENT.md). Change the code, change this page,
 * and the other way round. tests/privacy.test.ts holds the figures equal to
 * lib/report.ts's and the worker's.
 *
 * It names both processors, Cloudflare and our own server (the owner's
 * decision, November 2026). /how-we-crawl still does not name Cloudflare.
 *
 * Plain words, for Egypt's Personal Data Protection Law (Law No. 151 of 2020):
 * who is responsible, what is collected, why, for how long, who else sees it,
 * and what a person can ask for.
 */
import { CONTACT_EMAIL } from "@/lib/content/crawling";
import { EMAIL_KEPT_DAYS, IP_HASH_KEPT_HOURS } from "@/lib/report";

export const PRIVACY_UPDATED = "13 November 2026";

/** How long our web server's access log, with IP addresses, is kept. */
export const ACCESS_LOG_DAYS = 30;

/** How much longer a backup of the database may hold what is erased from it
 *  (scripts/lib/prune.sh, BACKUP_MAX_DAYS). */
export const BACKUP_DAYS = 30;

export type PrivacyBlock =
  | { kind: "p"; text: string }
  | { kind: "list"; items: string[] }
  | { kind: "table"; rows: { what: string; kept: string }[] };

export type PrivacySection = { id: string; title: string; blocks: PrivacyBlock[] };

export const privacyLead = [
  "makhzan is a free directory of Egyptian hardware and electronics shops. You can use it without an account, and makhzan sets no cookies.",
  "This page says what makhzan keeps about you, why, and for how long. It is written for Egypt’s Personal Data Protection Law (Law No. 151 of 2020).",
];

export const privacySections: PrivacySection[] = [
  {
    id: "who",
    title: "Who is responsible",
    blocks: [
      {
        kind: "p",
        text: `makhzan is made and run by Merope. For anything about your data, write to ${CONTACT_EMAIL}.`,
      },
    ],
  },
  {
    id: "browsing",
    title: "When you browse",
    blocks: [
      {
        kind: "list",
        items: [
          "No account, no sign-in, and no cookies of ours.",
          `Every visit to makhzan passes through Cloudflare, which provides our content delivery and security. So Cloudflare handles every request to makhzan, reports included, and sees your IP address, as any such service must. It may set a cookie of its own when it checks for bots.`,
          `Our web server keeps an access log of the requests it receives, with IP addresses, for ${ACCESS_LOG_DAYS} days, then deletes it. We use it to keep the site running and to deal with abuse.`,
          "We count page views, and clicks through to shops, with Umami, which we run ourselves. It sets no cookie and does not store your IP address. It records the page, the site that sent you here, your browser and device type, and your rough location (country or city). If your browser asks sites not to track it, it counts nothing.",
          "Your choice of light or dark theme, and of list or grid results, is kept in your own browser and never sent to us.",
          "Product photos load straight from each shop’s own website, so your browser asks that shop for the picture, as it would on their site.",
          "When you follow a link to a shop, you are on their site, and their own privacy policy applies.",
        ],
      },
    ],
  },
  {
    id: "reports",
    title: "When you report a problem",
    blocks: [
      {
        kind: "p",
        text: "The “Report a problem” form on a product page sends us what you choose is wrong, the offers you pick, anything you write in the text box, and your email if you give one. When it arrives, our server also saves a copy of the product and its offers as the page showed them (titles, shops and prices), because they can change later.",
      },
      {
        kind: "p",
        text: "What we use it for: a person reads every report. We use it to correct the page, and to improve how makhzan decides that two shops sell the same product: a report we have checked can become an example that teaches and tests that matching. A report nobody has checked is never used for that.",
      },
      {
        kind: "table",
        rows: [
          {
            what: "Your email, if you give one",
            kept: `Used only to reply about your report. Deleted ${EMAIL_KEPT_DAYS} days after you send it.`,
          },
          {
            what: "A scrambled form of your IP address",
            kept: `Used only to stop spam, by limiting how many reports one connection can send. Deleted after ${IP_HASH_KEPT_HOURS} hours. The reports themselves never hold your address, only this scrambled form; the access log above keeps addresses for ${ACCESS_LOG_DAYS} days.`,
          },
          {
            what: "The report itself, without your email",
            kept: "Kept, so a correction or a matching change can be checked later. It says nothing about who you are, unless you write it in the text box, so please don’t.",
          },
        ],
      },
      {
        kind: "p",
        text: `We back up the database by hand from time to time. Each time, we delete backups more than ${BACKUP_DAYS} days old, keeping only the newest, so a backup can hold this information past the limits above until a newer one replaces it.`,
      },
      {
        kind: "p",
        text: "The form loads nothing from anyone else and has no CAPTCHA. Your report travels through Cloudflare, like every request to makhzan, and is stored only on our server.",
      },
    ],
  },
  {
    id: "sharing",
    title: "Who else sees it",
    blocks: [
      {
        kind: "p",
        text: "Cloudflare handles your requests on our behalf, as described above. Beyond that, no one: we do not sell, rent or share what you send us, and we do not use it for advertising. Shops do not see reports or who sent them; if a report shows a shop’s listing is wrong, we may tell the shop what is wrong, never who said so.",
      },
    ],
  },
  {
    id: "rights",
    title: "What you can ask",
    blocks: [
      {
        kind: "p",
        text: `You can ask what we hold about you, ask us to correct or delete it, and object to how it is used. Write to ${CONTACT_EMAIL}. Because there are no accounts, tell us your report’s reference (it looks like R-1234) or the email you gave, so we can find it. You can also complain to Egypt’s Personal Data Protection Center.`,
      },
    ],
  },
  {
    id: "changes",
    title: "Changes",
    blocks: [
      {
        kind: "p",
        text: "If any of this changes, we change this page first, and the date at the top.",
      },
    ],
  },
];
