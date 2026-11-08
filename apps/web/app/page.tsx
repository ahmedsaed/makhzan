import {
  ExampleSearches,
  ForShops,
  HomeShops,
  HomeStats,
  HomeDepartments,
  HowItWorks,
  SeveralShops,
} from "@/components/home-sections";
import { Container } from "@/components/section";
import { SearchField } from "@/components/search-field";
import { SiteHeader } from "@/components/site-header";
import type { Metadata } from "next";

import { fetchCategories, fetchStats, fetchSuppliers, searchProducts } from "@/lib/api";
import { TAGLINE } from "@/lib/brand";
import { formatCount } from "@/lib/format";
import { departmentCards } from "@/lib/home";
import { homeDescription, homeJsonLd, pageMetadata } from "@/lib/metadata";
import { jsonLdText } from "@/lib/product";
import { listedShops } from "@/lib/shops";
import { absoluteUrl } from "@/lib/site";
import { departmentSummaries } from "@/lib/departments";

export async function generateMetadata(): Promise<Metadata> {
  const stats = await fetchStats().catch(() => null);
  // No title: the root layout's default is the home page's.
  return pageMetadata({ description: homeDescription(stats), path: "/", ownCard: true });
}

/** Products in the "sold by several shops" strip: one row of six on desktop. */
const SEVERAL_SHOPS = 6;

/**
 * Two jobs: take a query from someone who knows what they want, and show a
 * first-time visitor what makhzan is and what is in it without their having to
 * search. A headline, one large search with example queries, the totals; then
 * the departments and their biggest categories, products several shops sell, the
 * shops themselves, how it works, and a word for shop owners.
 *
 * Desktop uses the full container: the hero sits beside "How makhzan works",
 * and every section below spans the width. Phones read top to bottom, with the
 * explainer moved below the browsing sections so the departments stay near the top.
 *
 * Every section fails soft. Each fetch is caught on its own, and a section
 * whose data did not arrive is left out; with nothing at all the page is still
 * a working search box.
 */
export default async function HomePage() {
  const [categories, stats, shops, several] = await Promise.all([
    fetchCategories().catch(() => []),
    fetchStats().catch(() => null),
    fetchSuppliers().catch(() => null),
    searchProducts({
      q: "",
      minSuppliers: 2,
      inStock: true,
      sort: "supplier_count:desc",
      limit: SEVERAL_SHOPS,
    }).catch(() => null),
  ]);
  const rows = departmentSummaries(categories);
  const cards = departmentCards(categories);
  const listed = shops ? listedShops(shops) : [];
  const now = new Date();

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdText(homeJsonLd(absoluteUrl("/"))) }}
      />
      <SiteHeader search={false} />
      <main className="flex-1 pb-12">
        <Container className="flex flex-col gap-10 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-x-12 lg:gap-y-14">
          <section
            aria-label="Search"
            data-home-section="hero"
            className="flex flex-col gap-3 pt-6 sm:pt-12 lg:col-start-1 lg:row-start-1 lg:pb-2"
          >
            <h1 className="max-w-[24ch] text-[26px] leading-[1.15] font-extrabold sm:text-4xl lg:text-5xl lg:leading-[1.08]">
              {TAGLINE}
            </h1>
            <SearchField
              placeholder="ESP32, oil seal, digital caliper"
              className="mt-1 w-full lg:mt-3"
            />
            {stats && (
              <p className="text-sm text-ink-2 lg:hidden">
                <span className="tabular">{formatCount(stats.products)}</span> products from{" "}
                <span className="tabular">{formatCount(stats.suppliers)}</span> shops. Prices
                rechecked about weekly.
              </p>
            )}
            <HomeStats stats={stats} departments={cards.length} className="mt-2 hidden lg:grid" />
            <ExampleSearches className="mt-2" />
          </section>

          <HowItWorks className="max-lg:order-1 lg:col-start-2 lg:row-start-1 lg:mt-12 lg:self-start" />

          {cards.length > 0 && (
            <div className="lg:col-span-2">
              <HomeDepartments cards={cards} rows={rows} />
            </div>
          )}

          {several && several.hits.length > 0 && (
            <div className="lg:col-span-2">
              <SeveralShops hits={several.hits} total={several.total} now={now} />
            </div>
          )}

          {listed.length > 0 && (
            <div className="max-lg:order-2 lg:col-span-2">
              <HomeShops shops={listed} now={now} />
            </div>
          )}

          <ForShops className="max-lg:order-2 lg:col-span-2" />
        </Container>
      </main>
    </>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML — the caching
 * that matters happens in the fetch layer (see lib/api.ts), not in the page
 * shell.
 */
export const dynamic = "force-dynamic";
