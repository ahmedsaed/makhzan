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
 *
 * Every fact is stated once, in the section it belongs to. The at-a-glance
 * tiles summarise and link down; the questions at the end are short pointers
 * to the section that says it in full, never a second copy of it. Before
 * adding a sentence, look for the one that already says it.
 */

/**
 * Our robots.txt product token. The crawler matches robots.txt groups on it
 * whichever headers it sends (apps/ingestion/worker/robots.py), so this block
 * stops it on every shop, crawled as a browser or as makhzanbot.
 */
export const ROBOTS_TOKEN = "makhzanbot";
export const ROBOTS_BLOCK = `User-agent: ${ROBOTS_TOKEN}\nDisallow: /`;

/**
 * A mailbox that exists. The crawler and this page used to name an address on
 * a domain with no mail records, so a shop that wrote in got a bounce — the
 * worst possible answer to "who are you?".
 */
export const CONTACT_EMAIL = "crawler@makhzan.merope.dev";

/** Where the Web Bot Auth public keys are published (served by the API). */
export const KEY_DIRECTORY_PATH = "/.well-known/http-message-signatures-directory";

/**
 * Placeholder for the site's own origin in the copy below. The page replaces
 * it with SITE_URL at request time, so the copy never hard-codes a host.
 */
export const SITE = "{site}";

/** makhzanbot's User-Agent, as apps/ingestion/worker/identity.py sends it. */
export const USER_AGENT = `makhzanbot/1.0 (+${SITE}/how-we-crawl; ${CONTACT_EMAIL})`;

/** The "Crawler activity" section: measured figures, read from the API. */
export type ActivityContent = {
  heading: string;
  lead: string;
  gapNote: string;
  /** Shown in place of the figures when the API cannot give them. */
  unavailable: string;
  /** When the daily sweep is switched off: no next run to announce. */
  noNextRun: string;
  histogramHeading: string;
  histogramLead: string;
};

export type Glance = { label: string; value: string; note: string; href: string; mono?: boolean };
export type Pointer = { href: string; label: string };
export type Question = { question: string; answer: string; more: Pointer };

/** Ids of the page's sections, which are also its in-page links. */
export const SECTION = {
  read: "read",
  verify: "verify",
  robots: "robots",
  block: "block",
  pace: "pace",
  keep: "keep",
  prices: "prices",
  activity: "activity",
  suppliers: "suppliers",
  faq: "faq",
  contact: "contact",
} as const;

const at = (id: string) => `#${id}`;

/** The in-page navigation, in page order. */
export const CONTENTS: Pointer[] = [
  { href: at(SECTION.read), label: "What we read" },
  { href: at(SECTION.verify), label: "Recognise us" },
  { href: at(SECTION.robots), label: "robots.txt" },
  { href: at(SECTION.pace), label: "Our pace" },
  { href: at(SECTION.keep), label: "What we keep" },
  { href: at(SECTION.activity), label: "Crawler activity" },
  { href: at(SECTION.suppliers), label: "For suppliers" },
  { href: at(SECTION.faq), label: "Questions" },
  { href: at(SECTION.contact), label: "Contact" },
];

export const crawlingContent = {
  title: "How we crawl",
  lead: "makhzan is a directory. It shows what Egyptian suppliers publish and sends you to them to buy. Nothing is sold here, and no supplier pays to appear.",

  glance: [
    {
      label: "Who we are",
      value: "makhzanbot",
      note: "Signed requests",
      href: at(SECTION.verify),
      mono: true,
    },
    {
      label: "Pace",
      value: "1 request at a time",
      note: "At least 15 s apart, per shop",
      href: at(SECTION.pace),
    },
    {
      label: "A full pass",
      value: "About a week",
      note: "A slice a day, from 03:00 UTC",
      href: at(SECTION.pace),
    },
    {
      label: "What we keep",
      value: "Catalogue facts",
      note: "Never used to train AI, sold or licensed",
      href: at(SECTION.keep),
    },
  ] satisfies Glance[],
  glanceLinks: [
    { href: at(SECTION.activity), label: "See what we did this week" },
    { href: at(SECTION.suppliers), label: "Run a shop?" },
  ] satisfies Pointer[],

  read: {
    heading: "What we read",
    lead: "The same data you would see browsing the site yourself.",
    weRead:
      "Only the public catalogue pages and product APIs a shop already serves to any visitor.",
    weDoNot: [
      "create accounts, log in or place orders",
      "read anything behind a login",
      "collect anything about a supplier's customers",
    ],
  },

  verify: {
    heading: "How to recognise us, and check it is really us",
    lead: "Our crawler is called makhzanbot. We are moving shops to it one shop at a time.",
    requestLabel: "What a request from makhzanbot looks like",
    request: {
      start: `GET /shop/page/2 HTTP/1.1\nHost: your-shop.example`,
      userAgent: `User-Agent: ${USER_AGENT}`,
      from: `From: ${CONTACT_EMAIL}`,
      signature: [
        `Signature-Agent: "${SITE}"`,
        `Signature-Input: sig1=("@authority" "signature-agent");created=…;expires=…;nonce="…";keyid="…";alg="ed25519";tag="web-bot-auth"`,
        "Signature: sig1=:…:",
      ],
    },
    notes: {
      userAgent: {
        title: "Our name and where to read about us.",
        body: "On a shop that has been moved, every request carries this User-Agent.",
      },
      from: {
        title: "An address that reaches a person.",
        body: "Sent with every request, moved or not.",
      },
      signature: {
        title: "The signature that proves it is us.",
        body: "How to check it is under Web Bot Auth below.",
      },
    },
    tabsLabel: "Ways to identify makhzanbot",
    tabs: {
      userAgent: {
        label: "User-Agent",
        lead: "To search your logs for it:",
        snippet: USER_AGENT,
        notMoved:
          "On a shop not yet moved, our User-Agent still looks like a browser: look for the From header instead.",
      },
      robots: {
        label: "robots.txt",
        body: "Our robots.txt token is makhzanbot. Rules written for makhzanbot are obeyed on every shop we read, whichever User-Agent we send there, so a shop can address us by name.",
        snippet: ROBOTS_TOKEN,
        more: { href: at(SECTION.block), label: "The two lines that stop us altogether" },
      },
      signature: {
        label: "Web Bot Auth",
        body: "Requests from makhzanbot are signed with Web Bot Auth (RFC 9421 HTTP message signatures), which anyone can verify and nobody else can forge, whichever address a request comes from.",
        keyLead: "Our public key is published at:",
        snippet: `${SITE}${KEY_DIRECTORY_PATH}`,
      },
    },
    noAddresses: "We do not publish our IP addresses: the signature is the proof.",
  },

  robots: {
    heading: "We follow what each site publishes",
    lead: "A shop's robots.txt decides what we read on its site.",
    steps: [
      { tag: "Always", title: "Read robots.txt first", body: "Before fetching anything." },
      {
        tag: "Always",
        title: "Obey it",
        body: "A path a shop asks us not to read is not read.",
      },
      { tag: "If it can't be read", title: "Use the last copy we read", alt: true },
      { tag: "And without one", title: "Skip the site that day", alt: true },
    ] as { tag: string; title: string; body?: string; alt?: boolean }[],
    delayHeading: "Crawl-delay is a floor, not a target",
    delayBody:
      "A shop asking for 20 seconds between requests gets 20, even though our own default is longer than most crawlers use.",
    delayOurs: "Our default",
    delayShop: "Shop sets",
    blockHeading: "To stop us reading your site altogether",
    blockLead: "Add these two lines to your robots.txt:",
    block: ROBOTS_BLOCK,
  },

  pace: {
    heading: "We go slowly on purpose",
    lead: "One request at a time per shop, with a pause of at least 15 seconds between them.",
    trackLabel: "One shop, one request at a time",
    cycleLabel: "A full pass over a catalogue",
    cycleAlt:
      "A full pass is spread over about a week: a slice of the catalogue each day, starting at 03:00 UTC.",
    cycleDay: "Each day: a slice of the catalogue",
    cycleWeek: "About a week: the whole catalogue",
    cycleBody:
      "Spread out rather than run in one burst, so no shop sees a spike of traffic from us.",
    endOfPass:
      "If a supplier stops listing something, it drops out of makhzan after a full pass confirms it is gone.",
    pushbackHeading: "When a site pushes back",
    pushback: [
      { when: "It starts answering with errors", then: "We slow down rather than retry harder." },
      { when: "It asks us to wait", then: "We wait at least as long as it asks." },
      {
        when: "It asks for longer than ten minutes",
        then: "We stop for the day and pick up where we left off.",
      },
    ],
    hourHeading: "Early morning, Egypt time",
    hourBody: "Each day's run starts at 03:00 UTC, when shops are quietest.",
    hourAsk: { href: at(SECTION.suppliers), label: "A shop can ask for another hour or pace" },
  },

  keep: {
    heading: "What we keep, and what we do not do with it",
    lead: "Every product on makhzan links to the shop's own page, where people buy.",
    keepHeading: "For each product we keep",
    kept: [
      { item: "its name" },
      { item: "its price", note: "and how the price changes over time" },
      { item: "whether it is in stock" },
      { item: "its description and specifications" },
      { item: "links to its photos", note: "shown from the shop's own site" },
    ] as { item: string; note?: string }[],
    dontHeading: "We do not",
    dont: [
      "copy photos",
      "use what we read for anything but showing it here, with that link",
      "use shop content to train AI models, or sell or license it",
      "let AI training crawlers take it from our pages: our robots.txt refuses them",
    ],
    /** The line the old "we do not feed it to AI tools" over-promised: a
     * visitor's assistant reading a public page that it links back to is
     * reading, not being fed (robots.txt policy, 2026-11-13). */
    readers:
      "Search engines and AI assistants that link back to the shop may read our pages, as they can read the shop's own.",
    pricesTitle: "Prices here may be out of date.",
    pricesBody:
      "Every listing shows when we last checked it. We do not control supplier pricing and cannot guarantee a price is still current — always confirm on the supplier's own site before buying.",
  },

  activity: {
    heading: "Crawler activity",
    lead: "What our crawler did on each shop's site over the last 7 days, recorded as each request was sent. If you run one of these shops, you can check it against your own server logs.",
    gapNote:
      "A gap is the time between one request to a site and the next. The shortest and the typical (median) gap are both measured, not set. “—” means nothing was recorded for that shop this week: we began recording the gaps in November 2026. The line beside a count is requests per day (UTC); a day whose count was not recorded is left out of it, and a run counts on the day it started.",
    unavailable: "These figures can't be shown right now. Please check back in a few minutes.",
    noNextRun: "Not scheduled at the moment",
    histogramHeading: "How far apart our requests were this week",
    histogramLead:
      "Every gap between two requests to one site, all shops together, floored to the second.",
  } satisfies ActivityContent,

  suppliers: {
    heading: "If you are a supplier",
    lead: "We would rather have your permission than work around its absence.",
    cards: [
      {
        heading: "Change how we list or crawl you",
        body: "Write to us to be removed, listed differently, crawled more slowly, at a particular hour or fewer pages a day, and we will do it.",
      },
      {
        heading: "No descriptions or photos",
        body: "If you would rather we did not show your product descriptions or photos, say so and we will stop, keeping only the name, price and a link to your page.",
      },
      {
        heading: "If your site refuses our crawler",
        body: "We write to you rather than work around it: we never disguise our requests, change addresses or retry harder to get past a block.",
      },
      {
        heading: "Not listed yet?",
        body: "If you would like to be listed and are not yet, that is easier still.",
      },
    ],
  },

  faq: {
    heading: "Questions",
    lead: "Each answer points to where the page says it in full.",
    items: [
      {
        question: "Does makhzan sell these products?",
        answer: "No.",
        more: { href: "#top", label: "What makhzan is" },
      },
      {
        question: "How do I stop makhzanbot reading my site?",
        answer: "Two lines in your robots.txt, or write to us.",
        more: { href: at(SECTION.block), label: "The two lines" },
      },
      {
        question: "How can I tell a request really came from you?",
        answer: "Check its signature.",
        more: { href: at(SECTION.verify), label: "How to check" },
      },
      {
        question: "I can't find makhzanbot in my logs. Why?",
        answer: "Your shop may not have been moved yet.",
        more: { href: at(SECTION.verify), label: "What to look for" },
      },
      {
        question: "Do you use shop content to train AI?",
        answer: "No.",
        more: { href: at(SECTION.keep), label: "What we keep" },
      },
      {
        question: "Why might a price on makhzan be wrong?",
        answer: "It may be out of date.",
        more: { href: at(SECTION.prices), label: "Prices" },
      },
      {
        question: "What happens if my site blocks you?",
        answer: "We write to you.",
        more: { href: at(SECTION.suppliers), label: "If you are a supplier" },
      },
    ] satisfies Question[],
  },

  contactHeading: "Contact",
  contactBody: "Questions, corrections, or a request to change how we crawl your site:",
  contactEmail: CONTACT_EMAIL,
};

export type CrawlingContent = typeof crawlingContent;
