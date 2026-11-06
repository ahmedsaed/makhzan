import type { Metadata } from "next";
import { Link } from "@/components/link";
import { notFound } from "next/navigation";

import { labelFor } from "@/components/browse-menu";
import { ProductMedia } from "@/components/product-media";
import { ProductRows, rowFromSummary } from "@/components/product-row";
import { StockBadge } from "@/components/stock-badge";
import { Container, SectionHeading } from "@/components/section";
import {
  categoryNameOf,
  fetchProduct,
  fetchSimilar,
  supplierNameOf,
  titleOf,
  type Offer,
} from "@/lib/api";
import { formatPrice, relativeTime } from "@/lib/format";
import { getDictionary, isLang, localeOf, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * The page the whole system exists to render: one canonical product, every
 * supplier's offer, cheapest first.
 *
 * DOM order is media → header → offers → description → similar, which is the
 * phone order too. The offers panel must never sit below a supplier's prose;
 * comparing prices is why the page exists.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string; id: string }>;
}): Promise<Metadata> {
  const { lang, id } = await params;
  if (!isLang(lang)) return {};
  const product = await fetchProduct(id);
  if (!product) return {};
  const title = titleOf(product, lang) || product.part_number || "";
  return {
    title,
    alternates: {
      canonical: `/${lang}/products/${id}`,
      languages: { en: `/en/products/${id}`, ar: `/ar/products/${id}` },
    },
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<{ lang: string; id: string }>;
}) {
  const { lang, id } = await params;
  if (!isLang(lang)) notFound();
  const typed: Lang = lang;
  const t = getDictionary(typed);
  const locale = localeOf(typed);

  const product = await fetchProduct(id);
  if (!product) notFound();

  const similar = await fetchSimilar(id, 6).catch(() => []);
  const title = titleOf(product, typed) || product.part_number || "";
  const best = product.offers.find((offer) => offer.price !== null) ?? product.offers[0];

  return (
    <Container className="py-6">
      {product.category && (
        <nav className="mb-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          <Link href={routes.vertical(typed, product.category.domain)} className="hover:text-ink">
            {labelFor(product.category.domain, typed)}
          </Link>
          <span>›</span>
          <Link href={routes.category(typed, product.category.ref)} className="hover:text-ink">
            {categoryNameOf(product.category, typed)}
          </Link>
        </nav>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section className="lg:col-start-1 lg:row-start-1">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
            <ProductMedia
              src={product.image}
              alt={title}
              priority
              className="w-full border-2 sm:w-48 sm:shrink-0"
            />
            <div className="min-w-0">
              {product.part_number && (
                <span data-identifier className="font-mono text-xs text-accent">
                  {product.part_number}
                </span>
              )}
              <h1 className="mt-1 text-xl leading-tight sm:text-2xl">{title}</h1>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-muted">
                <StockBadge signal={product.in_stock ? "in_stock" : "unknown"} lang={typed} />
                {product.brand && (
                  <span>
                    {t.brandLabel}: {product.brand}
                  </span>
                )}
                {product.last_verified_at && (
                  <span>
                    {t.verified} {relativeTime(new Date(product.last_verified_at), locale)}
                  </span>
                )}
              </div>

              {product.min_price !== null && (
                <div className="mt-4 rounded-lg border-2 border-rule bg-surface px-3 py-2.5">
                  <p className="font-display text-[11px] tracking-widest text-ink-muted uppercase">
                    {t.priceRange}
                  </p>
                  <p data-numeric className="mt-0.5 font-mono text-lg text-ink">
                    {formatPrice(product.min_price, product.currency, typed)}
                    {product.max_price !== null && product.max_price !== product.min_price && (
                      <> — {formatPrice(product.max_price, product.currency, typed)}</>
                    )}
                  </p>
                  <p data-numeric className="text-[12px] text-ink-muted">
                    {product.supplier_count.toLocaleString(locale)} {t.suppliersCount}
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Second in the DOM, so it is above the description on a phone and in
            the right column on a wide screen. */}
        <aside className="lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <div className="rounded-lg border-2 border-rule bg-surface p-3">
            <h2 className="mb-2 font-display text-[11px] tracking-widest text-ink-muted uppercase">
              {product.offer_count.toLocaleString(locale)} {t.offers}
            </h2>
            <ul data-offers>
              {product.offers.map((offer) => (
                <OfferRow
                  key={offer.id}
                  offer={offer}
                  lang={typed}
                  best={offer.id === best?.id}
                  productTitle={title}
                />
              ))}
            </ul>
            {best?.source_url && (
              <a
                href={best.source_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="mt-3 block rounded-lg border-2 border-accent bg-accent px-4 py-2.5 text-center text-sm font-semibold text-accent-ink"
              >
                {best.supplier
                  ? `${t.visitNamed} ${supplierNameOf(best.supplier, typed)}`
                  : t.visitSupplier}
              </a>
            )}
            <p className="mt-2 text-[11.5px] text-ink-muted">{t.notSoldHere}</p>
          </div>
        </aside>

        <section className="lg:col-start-1 lg:row-start-2">
          {similar.length > 0 && (
            <>
              <div className="mb-1 flex flex-wrap items-baseline gap-x-2">
                <SectionHeading>{t.related}</SectionHeading>
                <span className="rounded border border-rule px-1.5 py-0.5 text-[10px] font-semibold tracking-wider text-ink-muted uppercase">
                  WIP
                </span>
              </div>
              {/* Same category, nearest price — a weak signal that currently
                  returns cooling fans next to a dev board. Kept visible and
                  labelled rather than quietly shipped as if it worked. */}
              <p className="-mt-2 mb-3 text-[12.5px] text-ink-muted">{t.relatedWip}</p>
              <ProductRows
                rows={similar.map((item) => rowFromSummary(item, typed))}
                lang={typed}
              />
            </>
          )}
        </section>
      </div>
    </Container>
  );
}

/**
 * One supplier's offer. The whole row is a link to that listing — a price you
 * cannot open is not much of an offer.
 *
 * The offer's own title is shown whenever it differs from the product's. A
 * supplier legitimately lists several variants of the same part, and without the
 * title those rows are three identical lines with different prices.
 *
 * Freshness sits here rather than on the product: a 12-day-old price and a
 * 2-day-old price are not equally trustworthy.
 */
function OfferRow({
  offer,
  lang,
  best,
  productTitle,
}: {
  offer: Offer;
  lang: Lang;
  best: boolean;
  productTitle: string;
}) {
  const t = getDictionary(lang);
  const locale = localeOf(lang);
  const supplier = offer.supplier;
  const offerTitle = titleOf(offer, lang);
  const distinct = offerTitle && offerTitle !== productTitle ? offerTitle : null;

  return (
    <li className={best ? "-mx-3 bg-chip px-3" : ""}>
      <Link
        href={routes.listing(lang, offer.id)}
        className="flex items-center gap-3 border-b border-rule py-2.5 hover:bg-chip/70"
      >
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="truncate text-sm font-semibold text-ink">
            {supplier ? supplierNameOf(supplier, lang) : "—"}
          </span>
          {distinct && <span className="truncate text-[11.5px] text-ink">{distinct}</span>}
          <span className="truncate text-[10.5px] text-ink-muted">
            {[supplier?.area, supplier?.governorate].filter(Boolean).join(", ")}
            {supplier?.area && " · "}
            {relativeTime(new Date(offer.last_verified_at), locale)}
          </span>
        </div>
        {offer.price === null ? (
          <span className="text-[11.5px] whitespace-nowrap text-ink-muted">
            {t.priceOnRequest}
          </span>
        ) : (
          <span data-numeric className="font-mono text-sm whitespace-nowrap text-ink">
            {formatPrice(offer.price, offer.currency, lang)}
          </span>
        )}
      </Link>
    </li>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to, and prerendering 57,000 products would be pointless
 * anyway. SSR still gives crawlers complete HTML — the caching that matters
 * happens in the fetch layer (see lib/api.ts), not in the page shell.
 */
export const dynamic = "force-dynamic";
