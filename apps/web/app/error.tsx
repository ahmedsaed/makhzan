"use client";

import { useEffect } from "react";

import { Detour } from "@/components/detour";
import { Container } from "@/components/section";
import { SiteHeader } from "@/components/site-header";

/**
 * Something failed while rendering — almost always the API being unreachable.
 * Say so plainly and offer a retry, then the same ways onward as the 404. It
 * renders inside the root layout only, hence its own header, whose search is
 * left out because the page carries the large one.
 */
export default function ErrorPage({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <>
      <SiteHeader search={false} />
      <main className="flex-1">
        <Container className="py-16 text-center">
          <h1 className="text-2xl sm:text-3xl">Something went wrong</h1>
          <p className="mx-auto mt-2 max-w-md text-[15px] leading-relaxed text-ink-2">
            The catalogue didn&apos;t answer. It is usually back within a minute.
          </p>
          <button
            type="button"
            onClick={() => unstable_retry()}
            className="mt-6 inline-flex h-11 items-center rounded-control border-[1.5px] border-line-strong bg-surface px-5 font-semibold text-ink hover:bg-ground"
          >
            Try again
          </button>
          <Detour />
        </Container>
      </main>
    </>
  );
}
