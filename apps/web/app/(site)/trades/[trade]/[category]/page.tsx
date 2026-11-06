import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { categoryNameOf, fetchCategories } from "@/lib/api";
import { joinRef, routes } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

import { TradeBrowse, type RawParams } from "../../_components/trade-browse";

/**
 * One category, addressed through its trade because category slugs are unique
 * per trade only. The trade page, narrowed to it.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ trade: string; category: string }>;
}): Promise<Metadata> {
  const { trade, category: slug } = await params;
  const categories = await fetchCategories(trade).catch(() => []);
  const category = categories.find((c) => c.slug === slug);
  return {
    // The trade disambiguates: "Accessories" is a category in several.
    title: `${category ? categoryNameOf(category) : slug} · ${tradeLabel(trade)}`,
    alternates: { canonical: routes.category(joinRef(trade, slug)) },
  };
}

export default async function CategoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ trade: string; category: string }>;
  searchParams: Promise<RawParams>;
}) {
  const { trade, category: slug } = await params;
  const ref = joinRef(trade, slug);
  const categories = await fetchCategories(trade);
  const category = categories.find((c) => c.ref === ref);
  if (!category) notFound();

  return (
    <TradeBrowse
      trade={trade}
      categories={categories}
      selected={category}
      params={await searchParams}
    />
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
