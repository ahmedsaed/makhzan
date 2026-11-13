/**
 * The site's robots.txt, as text. Served by app/robots.txt/route.ts; built
 * here so the unit tests can read it without a server.
 *
 * The policy (owner-approved 13 November 2026, "option A"): search engines and
 * AI search/answer bots are welcome; AI training crawlers and SEO backlink
 * crawlers are refused the whole site; filter-combination URLs are refused to
 * everyone. It is hand-written rather than Next's `MetadataRoute.Robots`
 * because that cannot emit a `Content-Signal` line.
 *
 * A crawler that matches a named group ignores the `*` group entirely, so every
 * named group that should keep the general rules repeats them.
 */

/**
 * AI training crawlers and SEO backlink crawlers, refused everything.
 *
 * Training crawlers copy the catalogue into a model and send nobody back to a
 * shop; that is not what the shops' catalogues are published here for. (Their
 * operators' *search* and *user-fetch* agents are a different token and are
 * welcome; see ANSWER_AGENTS.) SEO backlink crawlers build link indexes to sell
 * to marketers; a directory gains nothing from them, and in November 2026
 * SemrushBot and SERankingBacklinksBot alone were about 30% of the site's
 * traffic (proxy logs, 11 Nov). Each token is the one its operator documents.
 */
export const REFUSED_CRAWLERS = [
  // AI training
  "GPTBot",
  "ClaudeBot",
  "Amazonbot",
  "Reflectionbot",
  "ElevenlabsCrawler",
  "CCBot",
  "Google-Extended",
  "Applebot-Extended",
  "meta-externalagent",
  "Bytespider",
  // SEO backlink indexes
  "SemrushBot",
  "SERankingBacklinksBot",
  "DotBot",
  "AhrefsBot",
];

/**
 * Crawlers welcome under the general rules but asked to pace themselves: both
 * fetch heavily, and both honour `Crawl-delay` (Google does not, and is left
 * under `*`).
 */
export const PACED_CRAWLERS = ["Claude-SearchBot", "Bingbot"];
export const CRAWL_DELAY_SECONDS = 5;

/**
 * Search engines and AI search/answer agents: deliberately not named, so they
 * fall under `*`. Listed only so the tests can hold the file to it.
 */
export const ANSWER_AGENTS = [
  "OAI-SearchBot",
  "ChatGPT-User",
  "Claude-User",
  "PerplexityBot",
  "Perplexity-User",
  "Amzn-SearchBot",
  "Amzn-User",
  "Applebot",
  "Googlebot",
  "facebookexternalhit",
  "ElevenlabsBot",
];

/** Search and AI-answer use yes, training no (contentsignals.org). */
export const CONTENT_SIGNAL = "search=yes, ai-input=yes, ai-train=no";

/**
 * The results-page filters (lib/results-query.ts) that crawlers were walking
 * in combination on department, category and shop pages, about 10k requests a
 * day in November 2026. Each filtered view's canonical is the unfiltered page
 * (`pagedPath` in lib/metadata.ts), so none of them is a page a search engine
 * should keep, and their combinations are endless.
 *
 * `offset` (paging) is deliberately absent: the canonical keeps it, because
 * page 3 lists products page 1 does not, and crawling the pages is how an
 * engine reaches them. The sitemap lists only the bare paths, which no rule
 * here touches.
 */
export const FILTER_PARAMS = [
  "q",
  "category",
  "domain",
  "shop",
  "in_stock",
  "stale",
  "min_suppliers",
  "min_price",
  "max_price",
  "sort",
];

/** The results pages the filters apply to: departments (and the categories
 *  under them) and shops. `/departments*` also covers `/departments?…`. */
const FACETED_PATHS = ["/departments", "/shops"];

/**
 * The general Disallow lines. Search is infinite query space with nothing a
 * department or category page does not list (search pages also say `noindex`);
 * `/api/` is the JSON the browser fetches, not a page.
 *
 * A filter is refused wherever it sits in the query: `?sort=` first, or
 * `&sort=` after another parameter. `*` and `$` in paths are honoured by
 * Google, Bing, Yandex, Applebot and the AI operators that follow RFC 9309
 * (which standardises them); a crawler that reads them literally matches
 * nothing with these lines and is only kept off /search and /api/.
 */
export function disallowLines(): string[] {
  const facets = FACETED_PATHS.flatMap((path) =>
    FILTER_PARAMS.flatMap((param) => [`${path}*?${param}=`, `${path}*&${param}=`]),
  );
  return ["/search", "/api/", ...facets].map((path) => `Disallow: ${path}`);
}

export function robotsTxt(sitemapUrl: string): string {
  // No `Allow: /`: allowing is the default, and a first-match parser (CPython's
  // urllib.robotparser, which small fetchers use) would match it before any
  // Disallow and read the whole file as "allow everything".
  const general = disallowLines();
  const groups = [
    [
      "# Everyone: search engines and AI search/answer agents are welcome;",
      "# filter combinations, search and the API are not pages (13 Nov 2026).",
      "User-agent: *",
      `Content-Signal: ${CONTENT_SIGNAL}`,
      ...general,
    ],
    [
      "# Welcome, paced: the general rules repeated, since a named group",
      "# ignores the * group (13 Nov 2026).",
      ...PACED_CRAWLERS.map((agent) => `User-agent: ${agent}`),
      `Content-Signal: ${CONTENT_SIGNAL}`,
      `Crawl-delay: ${CRAWL_DELAY_SECONDS}`,
      ...general,
    ],
    [
      "# Refused: AI training crawlers and SEO backlink crawlers (13 Nov 2026).",
      ...REFUSED_CRAWLERS.map((agent) => `User-agent: ${agent}`),
      "Disallow: /",
    ],
  ];
  return [...groups.map((lines) => lines.join("\n")), `Sitemap: ${sitemapUrl}`].join("\n\n") + "\n";
}
