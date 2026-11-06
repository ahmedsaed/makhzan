import { FileText } from "lucide-react";

import { ShopLink } from "@/components/shop-link";
import type { ShopDetails as Details } from "@/lib/product";

/**
 * The specs and datasheets one shop published (rule C4): each section
 * only when there is something in it, and labelled with whose listing it came
 * from, because a spec row is the shop's statement, not ours.
 */
export function ShopDetails({ details, idSuffix = "" }: { details: Details; idSuffix?: string }) {
  const { offer, shopName, specs, datasheets } = details;
  const source = `From ${shopName}'s listing`;
  return (
    <>
      {specs.length > 0 && (
        <section data-specs aria-labelledby={`specs-heading${idSuffix}`} className="mt-6 lg:mt-5">
          <h2 id={`specs-heading${idSuffix}`} className="text-[15px]">
            Specifications
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-2">{source}</p>
          <dl className="mt-2 divide-y divide-line rounded-card border border-line bg-surface text-sm">
            {specs.map((row) => (
              <div
                key={row.name}
                data-spec
                className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3 px-3.5 py-2"
              >
                <dt dir="auto" className="break-words text-ink-2">
                  {row.name}
                </dt>
                <dd dir="auto" className="break-words text-ink">
                  {row.identifier ? <span data-identifier>{row.value}</span> : row.value}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {datasheets.length > 0 && (
        <section
          data-datasheets
          aria-labelledby={`datasheets-heading${idSuffix}`}
          className="mt-6 lg:mt-5"
        >
          <h2 id={`datasheets-heading${idSuffix}`} className="text-[15px]">
            {datasheets.length === 1 ? "Datasheet" : "Datasheets"}
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-2">{source}</p>
          <ul className="mt-1">
            {datasheets.map((doc) => (
              <li key={doc.url}>
                <ShopLink
                  href={doc.url}
                  shop={offer.supplier?.slug ?? ""}
                  data-datasheet
                  className="inline-flex min-h-11 max-w-full items-center gap-2 text-sm font-medium text-link underline"
                >
                  <FileText aria-hidden="true" className="size-4 shrink-0" />
                  <span className="min-w-0 break-words">{doc.label}</span>
                </ShopLink>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
