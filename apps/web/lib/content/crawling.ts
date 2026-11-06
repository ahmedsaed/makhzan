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

export type CrawlingSection = { heading: string; body: string[] };

export type CrawlingContent = {
  title: string;
  lead: string;
  sections: CrawlingSection[];
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
      ],
    },
    {
      heading: "We go slowly on purpose",
      body: [
        "One request at a time per shop, with a pause of at least 15 seconds between them. A full pass over a supplier's catalogue is spread across about a week rather than run in one burst, so no shop sees a spike of traffic from us.",
        "Each day's run starts early in the morning, Egypt time (03:00 UTC), when shops are quietest. A shop that prefers another hour, a slower pace or fewer pages a day can ask, and gets it.",
        "Our crawler identifies itself in every request and gives an address to write to, so anyone looking at their server logs can tell who we are.",
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
  contactHeading: "Contact",
  contactBody: "Questions, corrections, or a request to change how we crawl your site:",
  contactEmail: CONTACT_EMAIL,
};
