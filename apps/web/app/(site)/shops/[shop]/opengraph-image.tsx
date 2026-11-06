import { fetchSupplier } from "@/lib/api";
import { TAGLINE } from "@/lib/brand";
import { shopCardLines } from "@/lib/metadata";
import { OG_SIZE, renderCard } from "@/lib/og";

/** A shop's link preview: its name, its counts, and what it carries most. */

export const alt = "A shop on makhzan: how many products it lists, and how many are in stock";
export const size = OG_SIZE;
export const contentType = "image/png";
export const revalidate = 3600;

export default async function Image({ params }: { params: Promise<{ shop: string }> }) {
  const { shop } = await params;
  const supplier = await fetchSupplier(shop).catch(() => null);
  if (!supplier) return renderCard({ title: TAGLINE });
  const card = shopCardLines(supplier);
  return renderCard({ title: card.title, lead: card.detail, lines: [card.carries] });
}
