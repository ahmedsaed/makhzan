import { fetchProduct } from "@/lib/api";
import { productIdFrom } from "@/lib/routes";
import { TAGLINE } from "@/lib/brand";
import { productPrice, productTitle, productWhere } from "@/lib/metadata";
import { galleryImages } from "@/lib/product";
import { clampText, fetchPhoto, OG_SIZE, renderCard } from "@/lib/og";

/**
 * A product's link preview: its title, the price range, where it is sold, and
 * its photo.
 *
 * The photo is the one request this makes to a shop. Photos otherwise load
 * straight from the shops into visitors' browsers (docs/decisions/0003); one
 * fetch per generated card is acceptable because the card is cached (the
 * route revalidates, and the photo fetch itself is cached for a week), so a
 * link shared around a group chat costs the shop one request, not one per
 * viewer. A slow, missing or unreadable photo leaves the card without it.
 */

export const alt = "A makhzan product: its price range and the shops that sell it";
export const size = OG_SIZE;
export const contentType = "image/png";
/** At most a day; the product fetch's own, shorter lifetime (lib/api.ts) wins
 *  when it is shorter, so the price on the card tracks the page's. Either
 *  way the photo comes from the week-long fetch cache, not the shop. */
export const revalidate = 86400;

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const id = productIdFrom((await params).id);
  const product = await fetchProduct(id).catch(() => null);
  // An unknown or withdrawn product still gets a card: the site's own.
  if (!product || product.offers.length === 0) return renderCard({ title: TAGLINE });

  const photo = await fetchPhoto(galleryImages(product)[0] ?? null);
  return renderCard({
    title: clampText(productTitle(product), photo ? 80 : 100),
    lead: productPrice(product),
    lines: [productWhere(product)],
    photo,
  });
}
