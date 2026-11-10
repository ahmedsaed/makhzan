/**
 * Long-form copy for the /how-we-crawl page.
 *
 * Kept out of the page component so the copy can be read and corrected as
 * prose, without wading through markup.
 *
 * This page exists because publishing an aggregator invites the question, and
 * the honest answer here is a good one. It is also the page to point a supplier
 * at when they ask what we are doing — so it has to be accurate, not
 * aspirational. If any of it stops being true, change the crawler or change the
 * page.
 */

export type CrawlingSection = {
  heading: string;
  body: string[];
  /** Text to copy as it is (shown preformatted after the body). */
  snippet?: string;
};

/**
 * Our robots.txt product token. The crawler matches robots.txt groups on it
 * whichever headers it sends (apps/ingestion/worker/robots.py), so this block
 * stops it on every shop, crawled as a browser or as makhzanbot.
 */
export const ROBOTS_TOKEN = "makhzanbot";
export const ROBOTS_BLOCK = `User-agent: ${ROBOTS_TOKEN}\nDisallow: /`;

/** The "Crawler activity" section: measured figures, read from the API. */
export type ActivityContent = {
  heading: string;
  lead: string;
  gapNote: string;
  /** Shown in place of the figures when the API cannot give them. */
  unavailable: string;
  /** When the daily sweep is switched off: no next run to announce. */
  noNextRun: string;
};

export type CrawlingContent = {
  title: string;
  lead: string;
  sections: CrawlingSection[];
  activity: ActivityContent;
  contactHeading: string;
  contactBody: string;
  contactEmail: string;
};

/**
 * A mailbox that exists. The crawler and this page used to name an address on
 * a domain with no mail records, so a shop that wrote in got a bounce — the
 * worst possible answer to "who are you?".
 */
export const CONTACT_EMAIL = "crawler@merope.dev";

export const crawlingContent: CrawlingContent = {
  title: "How we crawl",
  lead: "makhzan is a directory. It shows what Egyptian suppliers publish and sends you to them to buy. Nothing is sold here, and no supplier pays to appear.",
  sections: [
    {
      heading: "What we read",
      body: [
        "Only the public catalogue pages and product APIs a shop already serves to any visitor — the same data you would see browsing the site yourself.",
        "We do not create accounts, log in, place orders, or read anything behind a login. We do not collect anything about a supplier's customers.",
      ],
    },
    {
      heading: "We follow what each site publishes",
      body: [
        "Before fetching anything we read the site's robots.txt and obey it. A path a shop asks us not to read is not read.",
        "If a site sets Crawl-delay, we treat it as a floor rather than a target: a shop asking for 20 seconds between requests gets 20, even though our own default is longer than most crawlers use.",
        "Our robots.txt token is makhzanbot. Rules written for makhzanbot are obeyed on every shop we read, starting now, so a shop can address us by name. To stop us reading your site altogether, add these two lines to your robots.txt:",
      ],
      snippet: ROBOTS_BLOCK,
    },
    {
      heading: "We go slowly on purpose",
      body: [
        "One request at a time per shop, with a pause of at least 15 seconds between them. A full pass over a supplier's catalogue is spread across about a week rather than run in one burst, so no shop sees a spike of traffic from us.",
        "Each day's run starts early in the morning, Egypt time (03:00 UTC), when shops are quietest. A shop that prefers another hour, a slower pace or fewer pages a day can ask, and gets it.",
        "Every request carries a From header with an address to write to. We are also moving, one shop at a time, from a browser-style User-Agent to one that names makhzanbot and links to this page. Until a shop is moved, our User-Agent there still looks like a browser.",
      ],
    },
    {
      heading: "Prices here may be out of date",
      body: [
        "Every listing shows when we last checked it. We do not control supplier pricing and cannot guarantee a price is still current — always confirm on the supplier's own site before buying.",
        "If a supplier stops listing something, it drops out of makhzan after a full pass confirms it is gone.",
      ],
    },
    {
      heading: "If you are a supplier",
      body: [
        "We would rather have your permission than work around its absence. If you would like to be removed, listed differently, crawled more slowly, or crawled at a particular hour, write to us and we will do it.",
        "If you would like to be listed and are not yet, that is easier still.",
      ],
    },
  ],
  activity: {
    heading: "Crawler activity",
    lead: "What our crawler did on each shop's site over the last 7 days, recorded as each request was sent. If you run one of these shops, you can check it against your own server logs.",
    gapNote:
      "A gap is the time between one request to a site and the next. The shortest and the typical (median) gap are both measured, not set. “—” means nothing was recorded for that shop this week: we began recording the gaps in November 2026.",
    unavailable: "These figures can't be shown right now. Please check back in a few minutes.",
    noNextRun: "Not scheduled at the moment",
  },
  contactHeading: "Contact",
  contactBody: "Questions, corrections, or a request to change how we crawl your site:",
  contactEmail: CONTACT_EMAIL,
};
