import type { Metadata } from "next";
import { Link } from "@/components/link";
import { notFound } from "next/navigation";

import { ProductMedia } from "@/components/product-media";
import { StockBadge } from "@/components/stock-badge";
import { Container } from "@/components/section";
import { categoryNameOf, fetchListing, supplierNameOf, titleOf } from "@/lib/api";
import { formatPrice, relativeTime } from "@/lib/format";
import { getDictionary, isLang, localeOf, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * One supplier's version of a product, and the last page before the buyer
 * leaves. It always offers the way back up to the comparison — without that it
 * is a dead end that competes with the supplier's own site.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string; id: string }>;
}): Promise<Metadata> {
  const { lang, id } = await params;
  if (!isLang(lang)) return {};
  const listing = await fetchListing(id);
  if (!listing) return {};
  return {
    title: titleOf(listing, lang) || listing.part_number || "",
    // A withdrawn listing keeps its URL so inbound links still land somewhere
    // useful, but it must not stay in the index.
    robots: listing.status === "active" ? undefined : { index: false, follow: true },
  };
}

export default async function ListingPage({
  params,
}: {
  params: Promise<{ lang: string; id: string }>;
}) {
  const { lang, id } = await params;
  if (!isLang(lang)) notFound();
  const typed: Lang = lang;
  const t = getDictionary(typed);
  const locale = localeOf(typed);

  const listing = await fetchListing(id);
  if (!listing) notFound();

  const title = titleOf(listing, typed) || listing.part_number || "";
  const description = typed === "ar" ? listing.description_ar : listing.description_en;
  const withdrawn = listing.status !== "active";

  return (
    <Container className="py-6">
      {withdrawn && (
        <div className="mb-5 rounded-lg border-2 border-rule bg-chip px-4 py-3">
          <p className="font-display text-sm font-bold text-ink">{t.withdrawn}</p>
          <p className="mt-0.5 text-[13px] text-ink-muted">{t.withdrawnHint}</p>
          {listing.product_id && (
            <Link
              href={routes.product(typed, listing.product_id)}
              className="mt-2 inline-block text-[13px] font-semibold text-accent underline"
            >
              {t.seeOtherOffers}
            </Link>
          )}
        </div>
      )}

      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <ProductMedia
          src={listing.images[0] ?? null}
          alt={title}
          priority
          className="w-full border-2 sm:w-60 sm:shrink-0"
        />

        <div className="min-w-0 flex-1">
          {listing.part_number && (
            <span data-identifier className="font-mono text-xs text-accent">
              {listing.part_number}
            </span>
          )}
          <h1 className="mt-1 text-xl leading-tight sm:text-2xl">{title}</h1>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-muted">
            <StockBadge signal={listing.stock_signal} lang={typed} />
            {listing.category && (
              <Link href={routes.category(typed, listing.category.ref)} className="hover:text-ink">
                {categoryNameOf(listing.category, typed)}
              </Link>
            )}
            <span>
              {t.verified} {relativeTime(new Date(listing.last_verified_at), locale)}
            </span>
          </div>

          {listing.price !== null && (
            <p className="mt-4">
              <span data-numeric className="font-mono text-2xl text-ink">
                {formatPrice(listing.price, listing.currency, typed)}
              </span>
              {/* The supplier's own unit, never a normalised one — see ADR 0002. */}
              {listing.unit && <span className="ms-1 text-sm text-ink-muted">/ {listing.unit}</span>}
            </p>
          )}

          {listing.supplier && (
            <p className="mt-3 text-sm text-ink-muted">
              <Link
                href={routes.supplier(typed, listing.supplier.slug)}
                className="font-semibold text-ink hover:underline"
              >
                {supplierNameOf(listing.supplier, typed)}
              </Link>
              {listing.supplier.area && <> · {listing.supplier.area}</>}
            </p>
          )}

          {listing.product_id && !withdrawn && (
            <Link
              href={routes.product(typed, listing.product_id)}
              className="mt-3 inline-block text-[13px] font-semibold text-accent hover:underline"
            >
              {t.seeOtherOffers} →
            </Link>
          )}

          {description && (
            <section className="mt-6">
              <h2 className="mb-1.5 font-display text-[11px] tracking-widest text-ink-muted uppercase">
                {t.description}
              </h2>
              <p className="max-w-prose text-sm leading-relaxed whitespace-pre-line text-ink-muted">
                {description}
              </p>
              <p className="mt-1.5 text-[11px] text-ink-muted">{t.descriptionSource}</p>
            </section>
          )}
        </div>
      </div>

      {/* The only action on the page, pinned within reach on a phone. */}
      {listing.source_url && !withdrawn && (
        <div className="sticky bottom-0 mt-6 border-t-2 border-rule bg-surface py-3">
          <a
            href={listing.source_url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="block rounded-lg border-2 border-accent bg-accent px-4 py-3 text-center text-sm font-semibold text-accent-ink"
          >
            {listing.supplier
              ? `${t.visitNamed} ${supplierNameOf(listing.supplier, typed)}`
              : t.visitSupplier}
          </a>
          <p className="mt-1.5 text-center text-[11px] text-ink-muted">{t.notSoldHere}</p>
        </div>
      )}
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to, and prerendering 57,000 products would be pointless
 * anyway. SSR still gives crawlers complete HTML — the caching that matters
 * happens in the fetch layer (see lib/api.ts), not in the page shell.
 */
export const dynamic = "force-dynamic";
