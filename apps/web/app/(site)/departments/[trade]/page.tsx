import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { fetchCategories } from "@/lib/api";
import { pageMetadata, tradeDescription, pagedPath } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

import { TradeBrowse, type RawParams } from "../_components/trade-browse";

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<{ trade: string }>;
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { trade } = await params;
  const categories = await fetchCategories(trade).catch(() => []);
  return pageMetadata({
    title: tradeLabel(trade),
    description: tradeDescription(trade, categories),
    path: pagedPath(routes.department(trade), await searchParams),
    ownCard: true,
  });
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
  // A failed fetch is not an unknown trade: the page says the catalogue is not
  // answering instead of claiming the trade does not exist.
  const categories = await fetchCategories(trade).catch(() => null);
  // An unknown trade has no categories — that is a 404, not an empty page.
  if (categories?.length === 0) notFound();

  return <TradeBrowse trade={trade} categories={categories} params={await searchParams} />;
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
