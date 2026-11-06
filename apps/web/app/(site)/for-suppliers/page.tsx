import type { Metadata } from "next";

import { Container } from "@/components/section";
import { CONTACT_EMAIL } from "@/lib/content/crawling";

export const metadata: Metadata = {
  title: "For suppliers",
  description: "Remove, add or correct a shop on makhzan.",
};

/** Placeholder: the remove / add / correct requests are built here next. Until
 *  then it already answers the one question that cannot wait — how to leave. */
export default function ForSuppliersPage() {
  return (
    <Container className="max-w-2xl py-10">
      <h1 className="text-2xl">For suppliers</h1>
      <p className="mt-2 text-ink-2">
        To remove your shop, add it, or correct its details, write to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`} className="text-link underline">
          {CONTACT_EMAIL}
        </a>
        .
      </p>
    </Container>
  );
}
