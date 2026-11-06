import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Freshness } from "@/components/freshness";
import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { PriceRange } from "@/components/price";
import { Container, Empty } from "@/components/section";
import { ShopLink } from "@/components/shop-link";
import { StockBadge } from "@/components/stock-badge";
import {
  categoryNameOf,
  fetchSupplier,
  fetchSupplierListings,
  titleOf,
  type Listing,
} from "@/lib/api";
import { formatCount } from "@/lib/format";
import { parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";

const PAGE_SIZE = 24;

/**
 * One shop and what makhzan has seen of it.
 *
 * Carried over from the previous design so the route works; the direction-D
 * shop page (stat tiles, the stale-data note, what it carries) is built on top
 * of this.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ shop: string }>;
}): Promise<Metadata> {
  const { shop } = await params;
  const supplier = await fetchSupplier(shop);
  return supplier ? { title: supplier.name } : {};
}

export default async function ShopPage({
  params,
  searchParams,
}: {
  params: Promise<{ shop: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { shop } = await params;
  const raw = await searchParams;
  const offsetRaw = Number.parseInt(
    (Array.isArray(raw.offset) ? raw.offset[0] : raw.offset) ?? "",
    10,
  );
  const offset = Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : 0;

  const supplier = await fetchSupplier(shop);
  if (!supplier) notFound();
  const page = await fetchSupplierListings(shop, { limit: PAGE_SIZE, offset });
  const items = page?.items ?? [];
  const total = page?.total ?? 0;
  const here = routes.shop(shop);
  const now = new Date();

  return (
    <Container className="py-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="self-start rounded-card border border-line bg-surface p-4">
          <h1 className="text-xl leading-tight">{supplier.name}</h1>
          <dl className="mt-4 flex flex-col gap-1.5 text-sm">
            {supplier.area && <Fact label="Area" value={supplier.area} />}
            {supplier.governorate && <Fact label="Governorate" value={supplier.governorate} />}
            <Fact label="Products" value={formatCount(supplier.listing_count)} />
          </dl>
          {supplier.website_url && (
            <ShopLink
              href={supplier.website_url}
              shop={supplier.slug}
              className="mt-4 flex h-11 items-center justify-center rounded-control bg-action px-4 font-semibold text-action-ink"
            >
              Visit the shop&apos;s site
            </ShopLink>
          )}
        </aside>

        <div className="min-w-0">
          {items.length === 0 ? (
            <Empty title="Nothing listed" />
          ) : (
            <ul className="-mx-4 border-t border-line bg-surface md:mx-0">
              {items.map((listing) => (
                <ShopListingRow key={listing.id} listing={listing} now={now} />
              ))}
            </ul>
          )}

          <nav aria-label="Pages" className="mt-5 flex items-center justify-between gap-3 text-sm">
            {offset > 0 ? (
              <Link
                href={offset - PAGE_SIZE > 0 ? `${here}?offset=${offset - PAGE_SIZE}` : here}
                className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
              >
                Previous
              </Link>
            ) : (
              <span />
            )}
            {offset + PAGE_SIZE < total && (
              <Link
                href={`${here}?offset=${offset + PAGE_SIZE}`}
                className="flex h-11 items-center rounded-control border border-line-strong px-4 hover:bg-surface"
              >
                Next
              </Link>
            )}
          </nav>
        </div>
      </div>
    </Container>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-2">{label}</dt>
      <dd className="tabular text-ink">{value}</dd>
    </div>
  );
}

/**
 * A listing opens its product, never the shop directly (rule P1). One the
 * grouping step left without a product has nowhere to open, so it is shown
 * but not linked.
 */
function ShopListingRow({ listing, now }: { listing: Listing; now: Date }) {
  const title = titleOf(listing) || listing.part_number || "";
  const body = (
    <>
      <PhotoFrame src={listing.images[0] ?? null} alt={title} size={72} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="line-clamp-2 text-[15px] leading-snug font-medium text-ink">{title}</span>
        <PriceRange min={listing.price} currency={listing.currency} className="text-base" />
        <span className="flex flex-wrap items-center gap-x-1.5 text-[13px] text-ink-2">
          <StockBadge signal={listing.stock_signal} />
          {listing.category && (
            <>
              <span aria-hidden="true">·</span>
              <span>{categoryNameOf(listing.category)}</span>
            </>
          )}
          <span aria-hidden="true">·</span>
          <Freshness lastVerified={parseVerified(listing.last_verified_at)} now={now} />
        </span>
      </div>
    </>
  );
  return (
    <li className="border-b border-line">
      {listing.product_id ? (
        <Link href={routes.product(listing.product_id)} className="flex gap-3 px-4 py-3 hover:bg-ground">
          {body}
        </Link>
      ) : (
        <div className="flex gap-3 px-4 py-3">{body}</div>
      )}
    </li>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
