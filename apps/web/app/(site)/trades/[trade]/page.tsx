import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { fetchCategories } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { asPhrase, insideOf, tradeLabel } from "@/lib/trades";

import { TradeBrowse, type RawParams } from "../_components/trade-browse";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ trade: string }>;
}): Promise<Metadata> {
  const { trade } = await params;
  const categories = await fetchCategories(trade).catch(() => []);
  const count = categories.reduce((sum, category) => sum + category.count, 0);
  const inside = insideOf(trade, categories);
  return {
    title: tradeLabel(trade),
    description:
      categories.length > 0
        ? `${formatCount(count)} products in ${tradeLabel(trade)} from Cairo's suppliers${
            inside.length > 0 ? `: ${asPhrase(inside)}` : ""
          }.`
        : undefined,
    alternates: { canonical: routes.trade(trade) },
  };
}

/** One trade: its groups, its biggest categories, and its products. */
export default async function TradePage({
  params,
  searchParams,
}: {
  params: Promise<{ trade: string }>;
  searchParams: Promise<RawParams>;
}) {
  const { trade } = await params;
  const categories = await fetchCategories(trade);
  // An unknown trade has no categories — that is a 404, not an empty page.
  if (categories.length === 0) notFound();

  return <TradeBrowse trade={trade} categories={categories} params={await searchParams} />;
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
