import { Link } from "@/components/link";

import { ProductMedia } from "@/components/product-media";
import type { ProductSummary, SearchHit } from "@/lib/api";
import { titleOf } from "@/lib/api";
import { formatPrice, relativeTime } from "@/lib/format";
import { getDictionary, localeOf, type Lang } from "@/lib/i18n";
import { routes } from "@/lib/routes";

/**
 * The row every list is built from.
 *
 * A row, not a card, because the job is comparison: the price sits in its own
 * end-aligned column so twenty-four of them line up. A grid of cards looks
 * nicer and compares worse — see docs/DESIGN.md.
 */
export type Row = {
  id: string;
  title: string;
  partNumber: string | null;
  image: string | null;
  minPrice: number | null;
  currency: string;
  supplierCount: number;
  inStock: boolean;
  verifiedAt: Date | null;
  /** Extra line under the title — supplier names on search, category elsewhere. */
  note?: string | null;
};

export function ProductRow({
  row,
  lang,
  priority = false,
}: {
  row: Row;
  lang: Lang;
  priority?: boolean;
}) {
  const t = getDictionary(lang);
  const locale = localeOf(lang);

  return (
    <li className="border-b border-rule">
      <Link
        href={routes.product(lang, row.id)}
        className="flex items-center gap-3 py-3 hover:bg-chip/60"
      >
        <ProductMedia
          src={row.image}
          alt={row.title}
          priority={priority}
          className="size-12 shrink-0 border-2"
        />

        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {row.partNumber && (
            <span data-identifier className="font-mono text-[11px] text-accent">
              {row.partNumber}
            </span>
          )}
          <h3 className="truncate text-sm leading-tight font-semibold text-ink">{row.title}</h3>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-ink-muted">
            {row.inStock && (
              <span className="rounded-full bg-ok-bg px-2 py-0.5 font-semibold text-ok">
                {t.inStock}
              </span>
            )}
            {row.note && <span className="truncate">{row.note}</span>}
            {row.verifiedAt && (
              <span>
                {t.verified} {relativeTime(row.verifiedAt, locale)}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end text-end">
          {row.minPrice === null ? (
            <span className="text-[11.5px] text-ink-muted">{t.priceOnRequest}</span>
          ) : (
            <>
              <span className="text-[10.5px] text-ink-muted">{t.from}</span>
              <span data-numeric className="font-mono text-sm text-ink">
                {formatPrice(row.minPrice, row.currency, lang)}
              </span>
            </>
          )}
          <span data-numeric className="text-[11px] text-ink-muted">
            {row.supplierCount.toLocaleString(locale)} {t.suppliersCount}
          </span>
        </div>
      </Link>
    </li>
  );
}

/** Search returns flat Meilisearch documents; the index stores the verified
 *  timestamp as epoch seconds. */
export function rowFromHit(hit: SearchHit, lang: Lang): Row {
  return {
    id: hit.id,
    title: titleOf(hit, lang) || hit.part_number || "",
    partNumber: hit.part_number,
    image: hit.image,
    minPrice: hit.min_price,
    currency: hit.currency,
    supplierCount: hit.supplier_count,
    inStock: hit.in_stock,
    verifiedAt: hit.last_verified_at ? new Date(hit.last_verified_at * 1000) : null,
    note: hit.supplier_name,
  };
}

export function rowFromSummary(product: ProductSummary, lang: Lang, note?: string | null): Row {
  return {
    id: product.id,
    title: titleOf(product, lang) || product.part_number || "",
    partNumber: product.part_number,
    image: product.image,
    minPrice: product.min_price,
    currency: product.currency,
    supplierCount: product.supplier_count,
    inStock: product.in_stock,
    verifiedAt: product.last_verified_at ? new Date(product.last_verified_at) : null,
    note,
  };
}

export function ProductRows({ rows, lang }: { rows: Row[]; lang: Lang }) {
  return (
    <ul className="border-t border-rule">
      {rows.map((row, index) => (
        <ProductRow key={row.id} row={row} lang={lang} priority={index < 3} />
      ))}
    </ul>
  );
}
