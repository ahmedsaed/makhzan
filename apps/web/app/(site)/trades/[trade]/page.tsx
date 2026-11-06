import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ObjectTile } from "@/components/object-tile";
import { Container, SectionHeading } from "@/components/section";
import { categoryNameOf, fetchCategories } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

/**
 * One page per trade. It answers "what does makhzan have in this trade" with
 * the category tree and its counts.
 *
 * Carried over from the previous design so the route works; the direction-D
 * trade page (group tiles, then results) is built on top of this.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ trade: string }>;
}): Promise<Metadata> {
  const { trade } = await params;
  return { title: tradeLabel(trade) };
}

export default async function TradePage({ params }: { params: Promise<{ trade: string }> }) {
  const { trade } = await params;

  const categories = await fetchCategories(trade);
  // An unknown trade has no categories — that is a 404, not an empty page.
  if (categories.length === 0) notFound();

  // Leaves hold the products; parents are browse groups.
  const leaves = categories
    .filter((category) => !categories.some((other) => other.parent === category.ref))
    .sort((a, b) => b.count - a.count);
  const total = categories.reduce((sum, category) => sum + category.count, 0);

  return (
    <Container className="py-8">
      <h1 className="text-2xl">{tradeLabel(trade)}</h1>
      <p className="mt-1 mb-6 text-sm text-ink-2">
        <span className="tabular">{formatCount(total)}</span> products
      </p>
      <SectionHeading>Categories</SectionHeading>
      <ul className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        {leaves.map((category) => (
          <li key={category.ref}>
            <ObjectTile
              href={routes.category(category.ref)}
              label={categoryNameOf(category)}
              count={category.count}
              size="sm"
            />
          </li>
        ))}
      </ul>
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
