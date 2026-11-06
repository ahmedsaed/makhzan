import type { Metadata } from "next";

import type { Category, Product, Stats, SupplierProfile } from "@/lib/api";
import { SITE_DESCRIPTION, SITE_NAME, TAGLINE } from "@/lib/brand";
import { formatCount, formatPriceRange, plural } from "@/lib/format";
import { summarizeOffers } from "@/lib/product";
import { tradesInWords } from "@/lib/shops";
import { asPhrase, insideOf, leavesOf, tradeLabel } from "@/lib/trades";

/**
 * The site's own card (app/opengraph-image.tsx), for pages without one.
 * Named here because a page that sets `openGraph` loses the root's image
 * along with the rest of it. A page with an `opengraph-image.tsx` of its own
 * must not name it: an explicit image replaces the file's.
 */
const SITE_CARD = {
  url: "/opengraph-image",
  width: 1200,
  height: 630,
  type: "image/png",
  alt: `${SITE_NAME}: find parts and materials across Egypt's suppliers`,
};

/**
 * What a page tells search engines and link previews about itself.
 *
 * Metadata merges shallowly between the layout and the page: a page that sets
 * `openGraph` replaces the layout's whole `openGraph`, site name, image and
 * all. So every page builds its block here, from one title, description and
 * path, and the three can never disagree between the tab, the canonical link
 * and the preview card.
 */
export function pageMetadata({
  title,
  description,
  path,
  noindex = false,
  ownCard = false,
}: {
  /** The page's segment has its own `opengraph-image.tsx`. */
  ownCard?: boolean;
  /** The page's own title; the root layout's template appends " · makhzan". */
  title?: string;
  description?: string;
  /** The canonical path, resolved against `metadataBase` (SITE_URL). */
  path?: string;
  /** For pages that are infinite query space: followed, never indexed. */
  noindex?: boolean;
}): Metadata {
  // A preview carries no template, so it names the site itself.
  const shared = title ? `${title} · ${SITE_NAME}` : undefined;
  return {
    ...(title !== undefined && { title }),
    ...(description !== undefined && { description }),
    ...(path !== undefined && { alternates: { canonical: path } }),
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      locale: "en",
      ...(shared && { title: shared }),
      ...(description && { description }),
      ...(path !== undefined && { url: path }),
      ...(!ownCard && { images: [SITE_CARD] }),
    },
    twitter: {
      card: "summary_large_image",
      ...(shared && { title: shared }),
      ...(description && { description }),
      ...(!ownCard && { images: [SITE_CARD] }),
    },
    ...(noindex && { robots: { index: false, follow: true } }),
  };
}

/**
 * schema.org for the home page: who runs the site, and how to search it, so a
 * search engine can offer a search box for it. `home` is the absolute URL of
 * `/`, on SITE_URL.
 */
export function homeJsonLd(home: string) {
  const url = new URL(home);
  const search = new URL("/search", url);
  return [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: SITE_NAME,
      url: url.toString(),
      logo: new URL("/icon-512.png", url).toString(),
      description: SITE_DESCRIPTION,
    },
    {
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: SITE_NAME,
      url: url.toString(),
      inLanguage: "en",
      potentialAction: {
        "@type": "SearchAction",
        // Built by hand: URLSearchParams would encode the braces.
        target: { "@type": "EntryPoint", urlTemplate: `${search}?q={search_term_string}` },
        "query-input": "required name=search_term_string",
      },
    },
  ];
}

// --------------------------------------------------------------------------- //
// Descriptions, from data the page fetched anyway
// --------------------------------------------------------------------------- //

const CHECKED = "Every price shows when it was last checked; buy on the shop's own page.";

/** "N products · N shops · rechecked weekly", for the site's own card. */
export function totalsLine(stats: Stats): string {
  return `${plural(stats.products, "product")} · ${plural(stats.suppliers, "shop")} · rechecked weekly`;
}

/** The home page: the tagline and the catalogue's size, when it answered. */
export function homeDescription(stats: Stats | null): string {
  if (!stats) return SITE_DESCRIPTION;
  return (
    `${TAGLINE} ${plural(stats.products, "product")} from ${plural(stats.suppliers, "shop")}, ` +
    `each price showing when it was last checked; buying happens on the shop's own site.`
  );
}

/** The title a product is shown under: its own, or its part number. */
export function productTitle(product: Product): string {
  return product.title_en || product.title_ar || product.part_number || "Untitled product";
}

/** Where a product's offers are: the one shop's name, or how many shops. */
export function productWhere(product: Product): string {
  const summary = summarizeOffers(product.offers);
  const sole = product.offers.length === 1 ? product.offers[0].supplier : null;
  return sole ? `at ${sole.name}` : `at ${plural(summary.shopCount, "shop")}`;
}

/** "EGP 75 – 110": the price range over the offers the summary counts. */
export function productPrice(product: Product): string {
  const summary = summarizeOffers(product.offers);
  return formatPriceRange(summary.min, summary.max, product.currency);
}

/**
 * "ESP32 Development Board 30 pin: EGP 260 – 300 at 3 shops in Egypt. …".
 * The price range and where are the two facts a buyer scanning results needs.
 */
export function productDescription(product: Product): string {
  const gone = summarizeOffers(product.offers).state === "out_of_stock" ? ", out of stock" : "";
  return `${productTitle(product)}: ${productPrice(product)} ${productWhere(product)} in Egypt${gone}. ${CHECKED}`;
}

/** A trade's product count and its biggest categories, or nothing to say. */
export function tradeDescription(domain: string, categories: Category[]): string | undefined {
  const own = categories.filter((category) => category.domain === domain);
  const count = own.reduce((sum, category) => sum + category.count, 0);
  if (count === 0) return undefined;
  const inside = insideOf(domain, own);
  const leaves = leavesOf(own).filter((category) => category.count > 0).length;
  return (
    `${formatCount(count)} products in ${tradeLabel(domain)} from Egypt's suppliers` +
    (inside.length > 0 ? `: ${asPhrase(inside)}` : "") +
    `. ${plural(leaves, "category", "categories")}, compared across shops.`
  );
}

/** A category's count, in its trade. */
export function categoryDescription(category: Category, total: number): string {
  return (
    `${plural(total, "product")} in ${category.name_en} (${tradeLabel(category.domain)}) ` +
    `from Egypt's suppliers, with prices compared across shops. ${CHECKED}`
  );
}

/** A shop's size, stock and what it carries. */
export function shopDescription(shop: SupplierProfile): string {
  const carries = shop.top_categories.slice(0, 3).map((category) => category.name_en);
  return (
    `${plural(shop.listing_count, "product")} from ${shop.name}, ${formatCount(shop.in_stock_count)} in stock` +
    (carries.length > 0 ? `: ${asPhrase(carries)}` : "") +
    `. Prices with when each was last checked; buy on the shop's own site.`
  );
}

/** A shop's card: its name, "4,340 products · 3,100 in stock", what it carries. */
export function shopCardLines(shop: SupplierProfile): {
  title: string;
  detail: string;
  carries: string | null;
} {
  const top = shop.top_categories.slice(0, 3).map((category) => category.name_en);
  return {
    title: shop.name,
    detail: `${plural(shop.listing_count, "product")} · ${formatCount(shop.in_stock_count)} in stock`,
    carries: top.length > 0 ? `${asPhrase(top)} and more` : tradesInWords(shop.domains) || null,
  };
}

/** A trade's card: its name, "1,580 products · 12 categories", what is inside. */
export function tradeCardLines(
  domain: string,
  categories: Category[],
): { title: string; detail: string | null; inside: string[] } {
  const own = categories.filter((category) => category.domain === domain);
  const count = own.reduce((sum, category) => sum + category.count, 0);
  const leaves = leavesOf(own).filter((category) => category.count > 0).length;
  return {
    title: tradeLabel(domain),
    detail:
      count > 0
        ? `${plural(count, "product")} · ${plural(leaves, "category", "categories")}`
        : null,
    inside: insideOf(domain, own, 3),
  };
}
