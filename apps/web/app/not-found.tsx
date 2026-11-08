import type { Metadata } from "next";

import { Detour } from "@/components/detour";
import { Container } from "@/components/section";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = { title: "Not found" };

/**
 * Renders inside the root layout only, so it brings its own header — without
 * its search, because the page carries the large one. Most visitors who land
 * here followed an old link to a product no shop lists any more, so the way
 * forward is a search, not an apology.
 */
export default function NotFound() {
  return (
    <>
      <SiteHeader search={false} />
      <main className="flex-1">
        <Container className="py-16 text-center">
          <p className="figure text-sm text-ink-3">404</p>
          <h1 className="mt-1 text-2xl sm:text-3xl">Page not found</h1>
          <p className="mx-auto mt-2 max-w-md text-[15px] leading-relaxed text-ink-2">
            The link may be old, or the product is no longer listed by any shop. Search for it, or
            browse by department or shop.
          </p>
          <Detour />
        </Container>
      </main>
    </>
  );
}
