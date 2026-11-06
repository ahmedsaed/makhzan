import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Breadcrumb } from "@/components/breadcrumb";
import { Freshness, StaleNote } from "@/components/freshness";
import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { PriceRange } from "@/components/price";
import { ResultRow } from "@/components/result";
import { Container, SectionHeading } from "@/components/section";
import { ShopLink } from "@/components/shop-link";
import { StockBadge } from "@/components/stock-badge";
import {
  categoryNameOf,
  fetchProduct,
  fetchSimilar,
  hitFromSummary,
  titleOf,
  type Offer,
} from "@/lib/api";
import { plural } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";
import { tradeLabel } from "@/lib/trades";

/**
 * One product and every shop's offer, cheapest first.
 *
 * Carried over from the previous design so the route works, on the shared
 * components; the direction-D product page (one-shop and several-shop forms,
 * the bottom bar) is built on top of this.
 *
 * DOM order is photo → header → offers → similar, which is the phone order
 * too: the offers must never sit below supplier prose.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const product = await fetchProduct(id);
  if (!product) return {};
  return {
    title: titleOf(product) || product.part_number || "",
    alternates: { canonical: routes.product(id) },
  };
}

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const product = await fetchProduct(id);
  if (!product) notFound();

  const similar = await fetchSimilar(id, 6).catch(() => []);
  const title = titleOf(product) || product.part_number || "";
  const now = new Date();
  const best = product.offers.find((offer) => offer.price !== null) ?? product.offers[0];

  return (
    <Container className="py-6">
      {product.category && (
        <Breadcrumb
          className="mb-3"
          items={[
            { label: tradeLabel(product.category.domain), href: routes.trade(product.category.domain) },
            { label: categoryNameOf(product.category), href: routes.category(product.category.ref) },
          ]}
        />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="flex flex-col gap-4 sm:flex-row sm:items-start lg:col-start-1 lg:row-start-1">
          <PhotoFrame src={product.image} alt={title} priority className="sm:w-56" />
          <div className="min-w-0">
            <h1 className="text-xl leading-tight sm:text-2xl">{title}</h1>
            {product.part_number && (
              <p className="mt-1 text-sm text-ink-2">
                Part number <span data-identifier>{product.part_number}</span>
              </p>
            )}
            <PriceRange
              min={product.min_price}
              max={product.max_price}
              currency={product.currency}
              className="mt-3 block text-2xl"
            />
            <p className="mt-1 text-[13px] text-ink-2">
              {plural(product.offer_count, "offer")} at {plural(product.supplier_count, "shop")}
            </p>
            <StaleNote
              className="mt-3"
              lastVerified={parseVerified(product.last_verified_at)}
              now={now}
            />
          </div>
        </section>

        {/* Second in the DOM, so it is above the similar products on a phone
            and in the right column on a wide screen. */}
        <aside className="lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <div className="rounded-card border border-line bg-surface p-3">
            <h2 className="mb-1 text-base">Offers</h2>
            <ul data-offers>
              {product.offers.map((offer) => (
                <OfferRow key={offer.id} offer={offer} productTitle={title} now={now} />
              ))}
            </ul>
            {best?.source_url && best.supplier && (
              <ShopLink
                href={best.source_url}
                shop={best.supplier.slug}
                className="mt-3 flex h-12 items-center justify-center rounded-control bg-action px-4 font-semibold text-action-ink"
              >
                View at {best.supplier.name}
              </ShopLink>
            )}
            <p className="mt-2 text-xs text-ink-2">
              makhzan doesn&apos;t sell anything — every offer opens the shop&apos;s own page.
            </p>
          </div>
        </aside>

        <section className="lg:col-start-1 lg:row-start-2">
          {similar.length > 0 && (
            <>
              <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
                <SectionHeading>Related products</SectionHeading>
                <span className="rounded-full border border-line-strong px-2 text-[11px] font-semibold text-ink-2">
                  WIP
                </span>
              </div>
              {/* Same category, nearest price — a weak signal. Kept visible and
                  labelled rather than quietly shipped as if it worked. */}
              <ul className="-mx-4 border-t border-line bg-surface md:mx-0">
                {similar.map((item) => (
                  <ResultRow key={item.id} hit={hitFromSummary(item)} now={now} />
                ))}
              </ul>
            </>
          )}
        </section>
      </div>
    </Container>
  );
}

/**
 * One shop's offer, led by its own title: a shop legitimately lists several
 * variants of one product, and without the title those rows are identical
 * lines with different prices (rule P3). Freshness sits here rather than on the
 * product, because a 12-day-old price and a 2-day-old one are not equally
 * trustworthy.
 */
function OfferRow({ offer, productTitle, now }: { offer: Offer; productTitle: string; now: Date }) {
  const supplier = offer.supplier;
  const offerTitle = titleOf(offer) || productTitle;

  return (
    <li className="flex items-center gap-3 border-b border-line py-2.5 last:border-b-0">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-[13px]">
        <span className="line-clamp-2 text-sm font-medium text-ink">{offerTitle}</span>
        <span className="flex flex-wrap items-center gap-x-1.5 text-ink-2">
          {supplier ? (
            <Link href={routes.shop(supplier.slug)} className="font-semibold hover:underline">
              {supplier.name}
            </Link>
          ) : (
            "Unknown shop"
          )}
          <span aria-hidden="true">·</span>
          <StockBadge signal={offer.stock_signal} />
          <span aria-hidden="true">·</span>
          <Freshness lastVerified={parseVerified(offer.last_verified_at)} now={now} />
        </span>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <PriceRange min={offer.price} currency={offer.currency} className="text-base" />
        {offer.source_url && supplier && (
          <ShopLink
            href={offer.source_url}
            shop={supplier.slug}
            className="flex h-9 items-center rounded-control border-[1.5px] border-link px-3 text-sm font-semibold text-link"
          >
            View
          </ShopLink>
        )}
      </div>
    </li>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
