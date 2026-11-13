/**
 * The about page's copy (/about): what makhzan is, how it works, who pays and
 * who runs it.
 *
 * Every claim here is held true elsewhere, and must change with it: the
 * weekly pass and one request at a time (lib/content/crawling.ts, the
 * worker's pacing); keeping uncertain matches apart and most products having
 * one shop (CLAUDE.md grouping, docs/DESIGN.md's 98.6%); no cart, payment or
 * delivery (docs/PLAN.md); free, no ads, nobody pays to appear or rank
 * (/for-suppliers); results ordered by relevance or the visitor's sort, never
 * by payment (the search API, the owner's promise of November 2026).
 *
 * The one live line is the catalogue's size (`catalogueLine`), from the API's
 * totals; without them it falls back to words, never to a zero.
 */
import type { Stats } from "@/lib/api";
import { HELLO_EMAIL } from "@/lib/content/contact";
import type { Rich } from "@/lib/content/prose";
import { plural } from "@/lib/format";
import { routes } from "@/lib/routes";

export const aboutLead =
  "makhzan is a directory of Egyptian hardware and electronics shops. Search once, and see what shops across Egypt list on their own websites: the price, whether it is in stock, and when we last checked.";

/** What the about page says of the catalogue's size when the API cannot say. */
export const CATALOGUE_FALLBACK = "It lists products from shops across Egypt.";

/**
 * "Today: 57,207 products from 8 shops in 16 departments." from the API's
 * totals and the number of departments with products in them. A department
 * count it could not get is left out; totals it could not get, or that read
 * zero (an empty or broken index, not an empty Egypt), give the fallback.
 */
export function catalogueLine(stats: Stats | null, departments: number | null): string {
  if (!stats || !(stats.products > 0) || !(stats.suppliers > 0)) return CATALOGUE_FALLBACK;
  const where = departments && departments > 0 ? ` in ${plural(departments, "department")}` : "";
  return `Today: ${plural(stats.products, "product")} from ${plural(stats.suppliers, "shop")}${where}.`;
}

export type AboutStep = { title: string; body: string; more?: { label: string; href: string } };

export type AboutSection = {
  id: string;
  title: string;
  /** Paragraphs before the steps or callout. */
  before?: Rich[];
  steps?: AboutStep[];
  callout?: string;
  after?: Rich[];
  /** Links set apart at the end, 44 px tall. */
  more?: { label: string; href: string }[];
};

export const aboutSections: AboutSection[] = [
  {
    id: "why",
    title: "Why it exists",
    before: [
      [
        "Parts and materials in Egypt are spread across many shops, each with its own website and its own search. Finding one sensor, fitting or breaker can mean opening shop after shop. makhzan puts their public catalogues into one search, so you can see who has it, then buy it from them.",
      ],
    ],
  },
  {
    id: "how",
    title: "How it works",
    steps: [
      {
        title: "We read shops’ public catalogues",
        body: "Our crawler reads the same public pages any visitor sees, obeys each shop’s robots.txt, and sends one request at a time. A full pass over every shop takes about a week.",
        more: { label: "How we crawl", href: routes.howWeCrawl() },
      },
      {
        title: "We match the same product across shops",
        body: "When several shops sell the same part, one page shows all their offers side by side. When we are not sure two listings are the same thing, we keep them apart: fewer shops on a page is better than a price range that is not real. Most products are sold by one listed shop.",
      },
      {
        title: "You go to the shop",
        body: "Every offer links to the shop’s own page. makhzan has no cart, takes no payment and delivers nothing: you buy from the shop and deal with them directly.",
      },
    ],
    after: [
      [
        "Prices and stock come from the shops’ sites and can change after we read them. Every offer says when it was checked; confirm on the shop’s site before you buy.",
      ],
    ],
  },
  {
    id: "money",
    title: "Who pays",
    callout: "makhzan is free, shows no ads, and no shop pays to be listed or to rank higher.",
    after: [
      [
        "Results are ordered by how well they match what you searched, or by the sort you choose, never by payment.",
      ],
    ],
  },
  {
    id: "who",
    title: "Who runs it",
    before: [
      [
        "makhzan is made and run by ",
        { link: "Merope", href: "https://merope.dev" },
        ". To get in touch, see ",
        { link: "Contact", href: routes.contact() },
        ", or write to ",
        { email: HELLO_EMAIL },
        ".",
      ],
    ],
  },
  {
    id: "shops",
    title: "If you run a shop",
    before: [
      [
        "You decide whether your shop is on makhzan. You can ask to be removed, added or corrected, and see exactly how we read your site.",
      ],
    ],
    more: [
      { label: "For suppliers", href: routes.forSuppliers() },
      { label: "How we crawl", href: routes.howWeCrawl() },
    ],
  },
];
