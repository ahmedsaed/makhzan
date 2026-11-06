import { ArrowUpRight, Clock } from "lucide-react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Link } from "@/components/link";
import { ResultList } from "@/components/result-list";
import { SearchField } from "@/components/search-field";
import { Container, SectionHeading } from "@/components/section";
import { ShopLink } from "@/components/shop-link";
import { fetchSupplier, fetchSupplierListings, type SupplierProfile } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { agoText, daysSince, freshnessTier, parseVerified } from "@/lib/freshness";
import { routes } from "@/lib/routes";
import {
  formatDay,
  hitFromListing,
  hostOf,
  isStale,
  shopSearchUrl,
  tradeShares,
} from "@/lib/shops";
import { cn } from "@/lib/utils";

/** How many in-stock products the page shows before handing off to search. */
const PREVIEW_SIZE = 6;

/**
 * One shop and what makhzan has seen of it.
 *
 * This page is the pitch to the shop as much as it is a page for buyers: the
 * owner is emailed a link to it (docs/PRODUCT.md). So it says plainly when
 * its data is old and why (F3), links out to the shop's own site, and tells the
 * owner how to add or correct their details.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ shop: string }>;
}): Promise<Metadata> {
  const { shop } = await params;
  const supplier = await fetchSupplier(shop);
  return supplier
    ? {
        title: supplier.name,
        description: `${formatCount(supplier.listing_count)} products from ${supplier.name}, with prices and when each was last checked.`,
      }
    : {};
}

export default async function ShopPage({ params }: { params: Promise<{ shop: string }> }) {
  const { shop } = await params;
  const [supplier, listings] = await Promise.all([
    fetchSupplier(shop),
    fetchSupplierListings(shop, { inStock: true, limit: PREVIEW_SIZE }),
  ]);
  if (!supplier) notFound();

  const now = new Date();
  const verified = parseVerified(supplier.last_verified_at);
  const stale = isStale(supplier.last_verified_at, now);
  const hits = (listings?.items ?? []).flatMap((listing) => hitFromListing(listing) ?? []);
  const location = [supplier.area, supplier.governorate].filter(Boolean).join(", ");

  return (
    <>
      <section className="border-b border-line bg-surface">
        <Container className="flex max-w-5xl flex-col gap-3 py-5">
          <div>
            <h1 className="text-2xl leading-tight sm:text-3xl">{supplier.name}</h1>
            {location && <p className="mt-1 text-sm text-ink-2">{location}</p>}
          </div>

          <dl className="grid grid-cols-3 gap-2 sm:max-w-xl">
            <Stat label="Products" value={formatCount(supplier.listing_count)} />
            <Stat label="In stock" value={formatCount(supplier.in_stock_count)} />
            <Stat
              label="Last checked"
              value={verified ? agoText(daysSince(verified, now)) : "Not yet"}
              tier={verified ? freshnessTier(verified, now) : "quiet"}
            />
          </dl>

          {stale && verified && (
            <p
              role="note"
              data-stale-note
              className="flex gap-2.5 rounded-control border border-warn-line bg-warn p-3 text-sm leading-snug text-warn-ink sm:max-w-xl"
            >
              <Clock aria-hidden="true" className="mt-px size-[18px] shrink-0" />
              <span>
                We can&apos;t reach this shop&apos;s site at the moment. Its prices and stock are as
                of {formatDay(verified, now)} and may have changed.
              </span>
            </p>
          )}

          {supplier.website_url && (
            <ShopLink
              href={supplier.website_url}
              shop={supplier.slug}
              className="flex h-11 items-center justify-center gap-2 rounded-control border-[1.5px] border-link px-4 font-semibold text-link hover:bg-ground sm:max-w-xl"
            >
              Visit {hostOf(supplier.website_url)}
              <ArrowUpRight aria-hidden="true" className="size-4" />
            </ShopLink>
          )}
        </Container>
      </section>

      <Container className="grid max-w-5xl gap-8 py-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <SearchField
            compact
            scope={{ shop: supplier.slug }}
            label={`Search ${supplier.name}`}
            placeholder={`Search ${supplier.name}`}
          />

          {supplier.domains.length > 0 && <Carries supplier={supplier} />}
        </div>

        <aside>
          {supplier.top_categories.length > 0 && (
            <section>
              <SectionHeading>Biggest categories here</SectionHeading>
              <ul className="overflow-hidden rounded-card border border-line bg-surface">
                {supplier.top_categories.map((category) => (
                  <li key={category.ref} className="border-b border-line last:border-b-0">
                    <Link
                      href={shopSearchUrl(supplier.slug, { category: category.ref })}
                      className="flex min-h-11 items-center gap-3 px-3 py-2 text-[15px] text-ink hover:bg-ground"
                    >
                      <span className="flex-1">{category.name_en}</span>
                      <span className="text-sm text-ink-3 tabular">
                        {formatCount(category.count)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </Container>

      <Container className="max-w-5xl pb-4">
        <section>
          <SectionHeading>In stock here</SectionHeading>
          {hits.length > 0 ? (
            <ResultList hits={hits} now={now} className="-mx-4 md:mx-0" />
          ) : (
            <p className="text-sm text-ink-2">Nothing from this shop is marked in stock.</p>
          )}
          {supplier.listing_count > 0 && (
            <Link
              href={shopSearchUrl(supplier.slug)}
              className="mt-3 inline-flex h-11 items-center text-sm font-semibold text-link hover:underline"
            >
              All {formatCount(supplier.listing_count)} products from {supplier.name}
            </Link>
          )}
        </section>

        <p className="mt-6 text-sm leading-relaxed text-ink-2">
          {location
            ? "Phone and opening hours aren't listed yet."
            : "Address and phone aren't listed yet."}{" "}
          <Link href={routes.forSuppliers()} className="font-semibold text-link hover:underline">
            Own this shop? Add your details.
          </Link>
        </p>
      </Container>
    </>
  );
}

/**
 * One figure in the row of three. The last-checked tile takes the freshness
 * colours (F2), so a stale shop is visible before a word of the note is read.
 */
function Stat({
  label,
  value,
  tier = "quiet",
}: {
  label: string;
  value: string;
  tier?: "quiet" | "muted" | "warn";
}) {
  return (
    <div
      data-tier={tier}
      className={cn(
        "rounded-control border p-2.5",
        tier === "warn" ? "border-warn-line bg-warn text-warn-ink" : "border-transparent bg-ground",
      )}
    >
      <dt className={cn("text-xs", tier === "warn" ? "text-warn-ink" : "text-ink-2")}>{label}</dt>
      <dd
        className={cn(
          "mt-0.5 figure text-[17px] leading-tight",
          tier === "warn" ? "text-warn-ink" : tier === "muted" ? "text-age-muted" : "text-ink",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/** Bar segments, largest first. Opacity steps of the one accent rather than new
 *  colours: the palette has none to spare, and order already says which is which. */
const SEGMENT = ["bg-action", "bg-action/55", "bg-action/30", "bg-ink-3/40"];

/**
 * What the shop carries: a bar by trade, and the same numbers in words. The
 * bar is decoration; the words are what a screen reader gets.
 */
function Carries({ supplier }: { supplier: SupplierProfile }) {
  const shares = tradeShares(supplier.domains);
  return (
    <section>
      <SectionHeading>What they carry</SectionHeading>
      <div aria-hidden="true" className="flex h-2 overflow-hidden rounded-full bg-line">
        {shares.map((share, index) => (
          <span
            key={share.domain ?? "other"}
            className={SEGMENT[Math.min(index, SEGMENT.length - 1)]}
            style={{ width: `${share.percent}%` }}
          />
        ))}
      </div>
      <p className="mt-2 text-[13px] text-ink-2">
        {shares.map((share, index) => (
          <span key={share.domain ?? "other"}>
            {index > 0 && " · "}
            {share.domain ? (
              <Link
                href={shopSearchUrl(supplier.slug, { domain: share.domain })}
                // 44px to tap on phones (S4), though it reads as a line of text.
                className="inline-flex min-h-11 items-center hover:text-ink hover:underline lg:min-h-0"
              >
                {share.label}
              </Link>
            ) : (
              share.label
            )}
          </span>
        ))}
      </p>
    </section>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
