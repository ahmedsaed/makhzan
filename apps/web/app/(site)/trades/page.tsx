import type { Metadata } from "next";

import { Container, Empty } from "@/components/section";
import { TradeList } from "@/components/trade-list";
import { fetchCategories } from "@/lib/api";
import { tradeSummaries } from "@/lib/trades";

export const metadata: Metadata = {
  title: "All trades",
  description: "Every trade makhzan covers, largest first, with what is inside each.",
};

/** Every trade as the home page lists its top eight: largest first, each
 *  saying what is inside. */
export default async function TradesPage() {
  const trades = tradeSummaries(await fetchCategories());

  return (
    <Container className="max-w-3xl py-5">
      <h1 className="mb-3 text-2xl">All {trades.length} trades</h1>
      {trades.length > 0 ? (
        <TradeList trades={trades} />
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
