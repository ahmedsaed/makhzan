import { fetchCategories } from "@/lib/api";
import { asPhrase } from "@/lib/trades";
import { tradeCardLines } from "@/lib/metadata";
import { OG_SIZE, renderCard } from "@/lib/og";

/**
 * A trade's link preview: its name, its size, and its biggest categories.
 * Category pages under it share this card; the trade is what they belong to.
 */

export const alt = "A trade on makhzan: how many products it holds, and its biggest categories";
export const size = OG_SIZE;
export const contentType = "image/png";
export const revalidate = 3600;

export default async function Image({ params }: { params: Promise<{ trade: string }> }) {
  const { trade } = await params;
  const categories = await fetchCategories(trade).catch(() => []);
  const card = tradeCardLines(trade, categories);
  return renderCard({
    title: card.title,
    lead: card.detail,
    lines: [card.inside.length > 0 ? `${asPhrase(card.inside)} and more` : null],
  });
}
