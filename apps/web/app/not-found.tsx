import { Link } from "@/components/link";
import { Container } from "@/components/section";
import { SiteHeader } from "@/components/site-header";
import { routes } from "@/lib/routes";

/** Renders inside the root layout only, so it brings its own header. */
export default function NotFound() {
  return (
    <>
      <SiteHeader />
      <main className="flex-1">
        <Container className="py-20 text-center">
          <h1 className="text-2xl">Not found</h1>
          <p className="mt-2 text-ink-2">
            That page doesn&apos;t exist, or the product is no longer listed by any shop.
          </p>
          <Link
            href={routes.home()}
            className="mt-6 inline-flex h-11 items-center rounded-control bg-action px-5 font-semibold text-action-ink"
          >
            Back to search
          </Link>
        </Container>
      </main>
    </>
  );
}
