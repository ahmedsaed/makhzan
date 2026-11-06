import type { Metadata } from "next";

import { Container } from "@/components/section";

export const metadata: Metadata = { title: "Shops" };

/** Placeholder: every shop with its products, in stock and last checked, is
 *  built here next. */
export default function ShopsPage() {
  return (
    <Container className="py-10">
      <h1 className="text-2xl">Shops</h1>
      <p className="mt-2 text-ink-2">
        Every shop makhzan lists, with how many products it has and when they were last checked.
      </p>
    </Container>
  );
}
