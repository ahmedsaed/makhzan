import { ArrowUpRight, Clock } from "lucide-react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Link } from "@/components/link";
import { NotAnswering, Results } from "@/components/results";
import { SearchField } from "@/components/search-field";
import { Container, SectionHeading } from "@/components/section";
import { ShopLink } from "@/components/shop-link";
import {
  categoryNameOf,
  fetchCategories,
  fetchCrawlerActivity,
  fetchSupplier,
  type Category,
  type CrawlerActivity,
  type SupplierProfile,
} from "@/lib/api";
import { absoluteTime, parseTime, shopActivityLine } from "@/lib/crawler-activity";
import { formatCount } from "@/lib/format";
import { agoText, daysSince, freshnessTier, parseVerified } from "@/lib/freshness";
import { pageMetadata, shopDescription, pagedPath } from "@/lib/metadata";
import { routes, withParams } from "@/lib/routes";
import {
  fetchResults,
  parseResultsQuery,
  type RawParams,
  type ResultsQuery,
} from "@/lib/results-query";
import { formatDay, hostOf, isStale, departmentShares } from "@/lib/shops";
import { cn } from "@/lib/utils";

import { DepartmentBar } from "../_components/department-bar";

/**
 * One shop and what makhzan has seen of it.
 *
 * This page is the pitch to the shop as much as it is a page for buyers: the
 * owner is emailed a link to it (docs/PRODUCT.md). So it says plainly when
 * its data is old and why (F3), links out to the shop's own site, and tells the
 * owner how to add or correct their details.
 *
 * Below the header band the page is the search page scoped to this shop
 * (components/results.tsx, on the lib/results-query.ts contract): chips, the
 * category and price rail on desktop, sort, list or grid, paging. The shop is
 * fixed by the path, and its name is left off every row, where it would only
 * repeat the heading.
 *
 * Stale products are hidden by default everywhere else (C2b), but not here
 * when the shop's own data is stale: the visitor asked for this shop, the note
 * in the header already says its data is old (F3), and the filter would
 * otherwise hide nearly everything, or show only the few products a fresher
 * shop also sells, which reads as the shop's catalogue having shrunk. The
 * "Recently checked" chip still turns it on. A shop that is up to date gets
 * the usual default; its products are fresh through its own offers anyway.
 */
export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<{ shop: string }>;
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { shop } = await params;
  const supplier = await fetchSupplier(shop);
  return supplier
    ? pageMetadata({
        title: supplier.name,
        description: shopDescription(supplier),
        path: pagedPath(routes.shop(supplier.slug), await searchParams),
        ownCard: true,
      })
    : {};
}

export default async function ShopPage({
  params,
  searchParams,
}: {
  params: Promise<{ shop: string }>;
  searchParams: Promise<RawParams>;
}) {
  const { shop } = await params;
  // The path decides the shop; a `?shop=` would only contradict it.
  const { shop: _ignored, ...raw } = await searchParams;
  void _ignored;
  // The shop first: whether its products hide when stale depends on it.
  const [supplier, categories, activity] = await Promise.all([
    fetchSupplier(shop),
    fetchCategories().catch((): Category[] => []),
    // Fails soft (null): the page is about the shop, and renders without it.
    fetchCrawlerActivity(),
  ]);
  if (!supplier) notFound();
  const query: ResultsQuery = {
    ...parseResultsQuery(raw, { freshByDefault: !isStale(supplier.last_verified_at) }),
    shop,
  };
  const data = await fetchResults(query);

  const pathname = routes.shop(supplier.slug);
  const names = new Map(categories.map((c) => [c.ref, categoryNameOf(c)]));
  const narrow = (key: "category" | "domain", value: string) =>
    withParams(pathname, raw, { [key]: value });

  return (
    <>
      <ShopHeader supplier={supplier} narrow={narrow} activity={activity} />

      <Container className="flex flex-col gap-6 py-6 lg:gap-4">
        {supplier.top_categories.length > 0 && (
          // Phones only: from `lg` the rail beside the results lists every
          // category with its count, so this would say the same thing twice.
          <section className="lg:hidden">
            <SectionHeading>Biggest categories here</SectionHeading>
            <ul className="overflow-hidden rounded-card border border-line bg-surface">
              {supplier.top_categories.map((category) => (
                <li key={category.ref} className="border-b border-line last:border-b-0">
                  <Link
                    href={narrow("category", category.ref)}
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

        <section data-shop-products>
          <SectionHeading className="lg:mb-4">Products</SectionHeading>
          {data.result ? (
            <Results
              pathname={pathname}
              raw={raw}
              query={query}
              data={{ ...data, result: data.result }}
              names={names}
              locked={["shop"]}
              shopName={supplier.name}
              hideShop
            />
          ) : (
            <NotAnswering />
          )}
        </section>

        <p className="text-sm leading-relaxed text-ink-2">
          {supplier.area || supplier.governorate
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
 * The band at the top. Phones: one column — name, figures, the stale note,
 * "Visit", search, what they carry. From `lg` it uses the width: the name and
 * search on the left, the figures and "Visit" on the right, and the note and
 * the department bar each across the whole band.
 */
function ShopHeader({
  supplier,
  narrow,
  activity,
}: {
  supplier: SupplierProfile;
  narrow: (key: "category" | "domain", value: string) => string;
  activity: CrawlerActivity | null;
}) {
  const now = new Date();
  const verified = parseVerified(supplier.last_verified_at);
  const stale = isStale(supplier.last_verified_at, now);
  const location = [supplier.area, supplier.governorate].filter(Boolean).join(", ");

  return (
    <section className="border-b border-line bg-surface">
      <Container className="flex flex-col gap-3 py-5 lg:grid lg:grid-cols-[minmax(0,1fr)_34rem] lg:gap-x-12 lg:gap-y-4 lg:py-7 lg:[grid-template-areas:'name_stats'_'search_visit'_'note_note'_'carries_carries'_'crawl_crawl']">
        <div className="lg:self-center lg:[grid-area:name]">
          <h1 className="text-2xl leading-tight sm:text-3xl lg:text-4xl">{supplier.name}</h1>
          {location && <p className="mt-1 text-sm text-ink-2">{location}</p>}
        </div>

        <dl className="grid grid-cols-3 gap-2 sm:max-w-xl lg:max-w-none lg:[grid-area:stats]">
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
            className="flex gap-2.5 rounded-control border border-warn-line bg-warn p-3 text-sm leading-snug text-warn-ink sm:max-w-xl lg:max-w-none lg:[grid-area:note]"
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
            className="flex h-11 items-center justify-center gap-2 rounded-control border-[1.5px] border-link px-4 font-semibold text-link hover:bg-ground sm:max-w-xl lg:max-w-none lg:[grid-area:visit]"
          >
            Visit {hostOf(supplier.website_url)}
            <ArrowUpRight aria-hidden="true" className="size-4" />
          </ShopLink>
        )}

        <SearchField
          compact
          scope={{ shop: supplier.slug }}
          label={`Search ${supplier.name}`}
          placeholder={`Search ${supplier.name}`}
          className="mt-2 sm:max-w-xl lg:mt-0 lg:max-w-none lg:[grid-area:search]"
        />

        {supplier.domains.length > 0 && (
          <Carries
            supplier={supplier}
            narrow={narrow}
            className="mt-2 lg:mt-1 lg:[grid-area:carries]"
          />
        )}

        <CrawlLine activity={activity} slug={supplier.slug} now={now} />
      </Container>
    </section>
  );
}

/**
 * What makhzan's crawler did on this shop's site, in one calm line, with the way
 * to the full record: "makhzan read this site 3 hours ago · 412 requests in the
 * last 7 days · at least 15 s apart · How we crawl". Nothing at all when the
 * activity could not be fetched, or the shop is not one we crawl.
 */
function CrawlLine({
  activity,
  slug,
  now,
}: {
  activity: CrawlerActivity | null;
  slug: string;
  now: Date;
}) {
  const shop = activity?.shops.find((s) => s.slug === slug);
  if (!activity || !shop) return null;
  const text = shopActivityLine(shop, activity.window_days, now).join(" · ");
  const lastRead = parseTime(shop.last_read_at);
  return (
    <p
      data-crawl-activity={shop.status}
      title={
        lastRead && shop.status === "active" ? `Last read ${absoluteTime(lastRead)}` : undefined
      }
      className="text-[13px] leading-relaxed text-ink-2 lg:[grid-area:crawl]"
    >
      {text}
      {/* A sentence ends with its full stop; figures run on with a dot. */}
      {text.endsWith(".") ? " " : " · "}
      <Link
        href={`${routes.howWeCrawl()}#activity`}
        // 44px to tap on phones (S4), though it reads as a line of text.
        className="inline-flex min-h-11 items-center font-semibold text-link hover:underline lg:min-h-0"
      >
        How we crawl
      </Link>
    </p>
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
        "rounded-control border p-2.5 lg:px-3.5 lg:py-3",
        tier === "warn" ? "border-warn-line bg-warn text-warn-ink" : "border-transparent bg-ground",
      )}
    >
      <dt className={cn("text-xs", tier === "warn" ? "text-warn-ink" : "text-ink-2")}>{label}</dt>
      <dd
        className={cn(
          "mt-0.5 figure text-[17px] leading-tight lg:text-xl",
          tier === "warn" ? "text-warn-ink" : tier === "muted" ? "text-age-muted" : "text-ink",
        )}
      >
        {value}
      </dd>
    </div>
  );
}

/**
 * What the shop carries: a bar by department, and the same numbers in words. The
 * bar is decoration; the words are what a screen reader gets. Each department
 * narrows the products below to it.
 */
function Carries({
  supplier,
  narrow,
  className,
}: {
  supplier: SupplierProfile;
  narrow: (key: "category" | "domain", value: string) => string;
  className?: string;
}) {
  const shares = departmentShares(supplier.domains);
  return (
    <section className={className}>
      <SectionHeading className="lg:mb-2 lg:font-sans lg:text-[13px] lg:font-semibold lg:text-ink-2">
        What they carry
      </SectionHeading>
      <DepartmentBar shares={shares} />
      <p className="mt-2 text-[13px] text-ink-2">
        {shares.map((share, index) => (
          <span key={share.domain ?? "other"}>
            {index > 0 && " · "}
            {share.domain ? (
              <Link
                href={narrow("domain", share.domain)}
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
