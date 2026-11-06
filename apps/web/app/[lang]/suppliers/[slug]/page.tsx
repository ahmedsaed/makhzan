import type { Metadata } from "next";
import { Link } from "@/components/link";
import { notFound } from "next/navigation";

import { ProductMedia } from "@/components/product-media";
import { StockBadge } from "@/components/stock-badge";
import { Container, Empty } from "@/components/section";
import {
  categoryNameOf,
  fetchSupplier,
  fetchSupplierListings,
  titleOf,
  type Listing,
} from "@/lib/api";
import { formatPrice } from "@/lib/format";
import { getDictionary, isLang, localeOf, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

const PAGE_SIZE = 24;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string; slug: string }>;
}): Promise<Metadata> {
  const { lang, slug } = await params;
  if (!isLang(lang)) return {};
  const supplier = await fetchSupplier(slug);
  return supplier ? { title: supplier.name } : {};
}

export default async function SupplierPage({
  params,
  searchParams,
}: {
  params: Promise<{ lang: string; slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { lang, slug } = await params;
  if (!isLang(lang)) notFound();
  const typed: Lang = lang;
  const t = getDictionary(typed);
  const locale = localeOf(typed);

  const raw = await searchParams;
  const offsetRaw = Number.parseInt(
    (Array.isArray(raw.offset) ? raw.offset[0] : raw.offset) ?? "",
    10,
  );
  const offset = Number.isFinite(offsetRaw) && offsetRaw > 0 ? offsetRaw : 0;

  const supplier = await fetchSupplier(slug);
  if (!supplier) notFound();
  const page = await fetchSupplierListings(slug, { limit: PAGE_SIZE, offset });
  const items = page?.items ?? [];
  const total = page?.total ?? 0;

  return (
    <Container className="py-6">
      <div className="grid gap-6 lg:grid-cols-[17rem_1fr]">
        <aside className="rounded-lg border-2 border-rule bg-surface p-4">
          <h1 className="text-xl leading-tight">{supplier.name}</h1>
          {supplier.name_ar && (
            <p dir="rtl" className="mt-0.5 text-sm text-ink-muted">
              {supplier.name_ar}
            </p>
          )}
          <dl className="mt-4 flex flex-col gap-1.5 text-sm">
            {supplier.area && <Fact label={t.area} value={supplier.area} />}
            {supplier.governorate && <Fact label={t.governorate} value={supplier.governorate} />}
            <Fact
              label={t.supplierListings}
              value={supplier.listing_count.toLocaleString(locale)}
              numeric
            />
          </dl>
          {supplier.website_url && (
            <a
              href={supplier.website_url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="mt-4 block rounded-lg border-2 border-accent bg-accent px-4 py-2.5 text-center text-sm font-semibold text-accent-ink"
            >
              {t.visitWebsite}
            </a>
          )}
        </aside>

        <div>
          {items.length === 0 ? (
            <Empty title={t.noResults} />
          ) : (
            <ul className="border-t border-rule">
              {items.map((listing) => (
                <SupplierListingRow key={listing.id} listing={listing} lang={typed} />
              ))}
            </ul>
          )}

          <nav className="mt-5 flex items-center justify-between gap-3 text-sm">
            {offset > 0 ? (
              <Link
                href={`${routes.supplier(typed, slug)}?offset=${Math.max(0, offset - PAGE_SIZE)}`}
                className="rounded-lg border border-rule px-3 py-1.5 hover:bg-chip"
              >
                ←
              </Link>
            ) : (
              <span />
            )}
            {offset + PAGE_SIZE < total && (
              <Link
                href={`${routes.supplier(typed, slug)}?offset=${offset + PAGE_SIZE}`}
                className="rounded-lg border border-rule px-3 py-1.5 hover:bg-chip"
              >
                →
              </Link>
            )}
          </nav>
        </div>
      </div>
    </Container>
  );
}

function Fact({ label, value, numeric }: { label: string; value: string; numeric?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd {...(numeric ? { "data-numeric": true } : {})} className="text-ink">
        {value}
      </dd>
    </div>
  );
}

function SupplierListingRow({ listing, lang }: { listing: Listing; lang: Lang }) {
  const title = titleOf(listing, lang) || listing.part_number || "";
  return (
    <li className="border-b border-rule">
      <Link
        href={routes.listing(lang, listing.id)}
        className="flex items-center gap-3 py-3 hover:bg-chip/60"
      >
        <ProductMedia
          src={listing.images[0] ?? null}
          alt={title}
          className="size-12 shrink-0 border-2"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {listing.part_number && (
            <span data-identifier className="font-mono text-[11px] text-accent">
              {listing.part_number}
            </span>
          )}
          <h3 className="truncate text-sm leading-tight font-semibold text-ink">{title}</h3>
          <div className="flex flex-wrap items-center gap-x-2 text-[11.5px] text-ink-muted">
            <StockBadge signal={listing.stock_signal} lang={lang} />
            {listing.category && <span>{categoryNameOf(listing.category, lang)}</span>}
          </div>
        </div>
        {listing.price !== null && (
          <span data-numeric className="font-mono text-sm whitespace-nowrap text-ink">
            {formatPrice(listing.price, listing.currency, lang)}
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
