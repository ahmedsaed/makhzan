"use client";

import { useEffect } from "react";

import { Container } from "@/components/section";
import { SiteHeader } from "@/components/site-header";

/**
 * Something failed while rendering — almost always the API being unreachable.
 * Say so plainly and offer a retry; the header still works, so search is one
 * step away. It renders inside the root layout only, hence its own header.
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
      <SiteHeader />
      <main className="flex-1">
        <Container className="py-20 text-center">
          <h1 className="text-2xl">Something went wrong</h1>
          <p className="mt-2 text-ink-2">
            The catalogue didn&apos;t answer. It is usually back within a minute.
          </p>
          <button
            type="button"
            onClick={() => unstable_retry()}
            className="mt-6 inline-flex h-11 items-center rounded-control bg-action px-5 font-semibold text-action-ink"
          >
            Try again
          </button>
        </Container>
      </main>
    </>
  );
}
