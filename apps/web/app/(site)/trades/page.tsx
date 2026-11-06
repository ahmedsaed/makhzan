import type { Metadata } from "next";

import { Container } from "@/components/section";

export const metadata: Metadata = { title: "Trades" };

/** Placeholder: all 16 trades, each saying what's inside, is built here next. */
export default function TradesPage() {
  return (
    <Container className="py-10">
      <h1 className="text-2xl">Trades</h1>
      <p className="mt-2 text-ink-2">
        Every trade makhzan covers, largest first, with what is inside each.
      </p>
    </Container>
  );
}
