import { Link } from "@/components/link";
import { SearchField } from "@/components/search-field";
import { Container } from "@/components/section";
import { routes } from "@/lib/routes";

/**
 * An unknown product id, or a redirect retired after a year unused (see
 * `loadProduct` in page.tsx; a withdrawn product has a page of its own). A 404
 * status, but not a dead end: someone who followed an old link most likely
 * still wants the part, so the search is right here.
 */
export default function ProductNotFound() {
  return (
    <Container className="max-w-2xl py-16 text-center">
      <h1 className="text-2xl">Not found</h1>
      <p className="mt-2 text-ink-2">
        No shop lists this product any more, or the link is wrong. Search for the part by name or
        part number:
      </p>
      <SearchField className="mt-6 text-start" />
      <Link
        href={routes.home()}
        className="mt-6 inline-flex h-11 items-center text-sm font-medium text-link underline"
      >
        Back to the home page
      </Link>
    </Container>
  );
}
