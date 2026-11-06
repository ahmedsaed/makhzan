import type { Metadata } from "next";

import { NotAnswering } from "@/components/results";
import { Container, Empty } from "@/components/section";
import { fetchCategories } from "@/lib/api";
import { formatCount, plural } from "@/lib/format";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import { tradeDirectory } from "@/lib/trade-directory";

import { TradeDirectory } from "./_components/trade-directory";

export async function generateMetadata(): Promise<Metadata> {
  const categories = await fetchCategories().catch(() => null);
  const trades = categories ? tradeDirectory(categories) : [];
  const products = trades.reduce((sum, trade) => sum + trade.count, 0);
  const names = trades.slice(0, 4).map((trade) => trade.label);
  return pageMetadata({
    title: "All trades",
    description:
      trades.length > 0
        ? `${plural(trades.length, "trade")} and ${plural(products, "product")} from Egypt's suppliers, largest first: ${names.join(", ")} and more, each with its categories and how much each holds.`
        : "Every trade makhzan covers, largest first, with its categories and how much each holds.",
    path: routes.trades(),
  });
}

/** Every trade as a directory: largest first, each with its categories as links. */
export default async function TradesPage() {
  const categories = await fetchCategories().catch(() => null);
  if (!categories) {
    return (
      <Container className="py-5">
        <h1 className="mb-3 text-2xl">All trades</h1>
        <NotAnswering title="The catalogue is not answering" />
      </Container>
    );
  }
  const trades = tradeDirectory(categories);
  const products = trades.reduce((sum, trade) => sum + trade.count, 0);
  const listed = trades.reduce((sum, trade) => sum + trade.categoryCount, 0);

  return (
    <Container className="py-5 md:py-6">
      <div className="mb-3 flex flex-col gap-0.5 md:mb-4 md:flex-row md:items-baseline md:gap-3">
        <h1 className="text-2xl">All {trades.length} trades</h1>
        {trades.length > 0 && (
          <p data-directory-total className="text-[13px] text-ink-3 tabular">
            {formatCount(products)} products in {formatCount(listed)} categories, largest trade
            first
          </p>
        )}
      </div>
      {trades.length > 0 ? (
        <TradeDirectory trades={trades} />
      ) : (
        <Empty title="No trades yet" hint="The catalogue is empty right now." />
      )}
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
