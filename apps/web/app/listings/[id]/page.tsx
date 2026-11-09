import { notFound, permanentRedirect } from "next/navigation";

import { fetchListing, fetchProduct, fetchProductRedirect, titleOf } from "@/lib/api";
import { routes } from "@/lib/routes";

/**
 * There are no listing pages any more: a listing is one shop's offer, and the
 * product page shows every offer with its freshness. Old links — shared,
 * bookmarked, indexed — still resolve, to the product the listing belongs to.
 * A withdrawn listing keeps its product, whose page then says it is no longer
 * listed; one whose product was merged away goes to the product it was merged
 * into.
 *
 * A page rather than a rule in proxy.ts because the target needs an API call,
 * and a page can answer a real 404 with the site's own not-found page when the
 * listing is gone or was never grouped. Outside the `(site)` group, so nothing
 * renders before the redirect and it goes out as a 308 rather than a meta
 * refresh.
 */
export default async function ListingRedirect({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const listing = await fetchListing(id);
  if (!listing?.product_id) notFound();
  // To the product's readable URL in one hop; the bare id would redirect again,
  // and so would a merged-away one.
  let productId = listing.product_id;
  let product = await fetchProduct(productId).catch(() => null);
  if (!product) {
    const moved = await fetchProductRedirect(productId).catch(() => null);
    if (moved) {
      productId = moved;
      product = await fetchProduct(moved).catch(() => null);
    }
  }
  permanentRedirect(
    routes.product(productId, product && (titleOf(product) || product.part_number)),
  );
}

export const dynamic = "force-dynamic";
