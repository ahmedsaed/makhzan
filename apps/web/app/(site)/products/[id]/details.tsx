import type { DetailSource } from "@/lib/product";
import { cn } from "@/lib/utils";

import { EdgeFade } from "./carousel";
import { Description } from "./description";
import { ShopDetails } from "./shop-details";

/*
 * Tailwind only generates classes it can read in the source, so each tab's
 * selectors are spelled out. The section is a named group, and `:has()` on it
 * asks which radio is checked, so a radio, its label and its panel need not be
 * siblings: the radios can sit inside the scrolling tab strip with their labels.
 */
const PANEL = [
  "group-has-[#details-source-0:checked]/details:block",
  "group-has-[#details-source-1:checked]/details:block",
  "group-has-[#details-source-2:checked]/details:block",
  "group-has-[#details-source-3:checked]/details:block",
  "group-has-[#details-source-4:checked]/details:block",
  "group-has-[#details-source-5:checked]/details:block",
  "group-has-[#details-source-6:checked]/details:block",
  "group-has-[#details-source-7:checked]/details:block",
];
const TAB = [
  "group-has-[#details-source-0:checked]/details:border-action group-has-[#details-source-0:checked]/details:text-ink group-has-[#details-source-0:focus-visible]/details:outline-2",
  "group-has-[#details-source-1:checked]/details:border-action group-has-[#details-source-1:checked]/details:text-ink group-has-[#details-source-1:focus-visible]/details:outline-2",
  "group-has-[#details-source-2:checked]/details:border-action group-has-[#details-source-2:checked]/details:text-ink group-has-[#details-source-2:focus-visible]/details:outline-2",
  "group-has-[#details-source-3:checked]/details:border-action group-has-[#details-source-3:checked]/details:text-ink group-has-[#details-source-3:focus-visible]/details:outline-2",
  "group-has-[#details-source-4:checked]/details:border-action group-has-[#details-source-4:checked]/details:text-ink group-has-[#details-source-4:focus-visible]/details:outline-2",
  "group-has-[#details-source-5:checked]/details:border-action group-has-[#details-source-5:checked]/details:text-ink group-has-[#details-source-5:focus-visible]/details:outline-2",
  "group-has-[#details-source-6:checked]/details:border-action group-has-[#details-source-6:checked]/details:text-ink group-has-[#details-source-6:focus-visible]/details:outline-2",
  "group-has-[#details-source-7:checked]/details:border-action group-has-[#details-source-7:checked]/details:text-ink group-has-[#details-source-7:focus-visible]/details:outline-2",
];

/**
 * What the shops wrote about the product: description, specs and datasheets,
 * one shop at a time, each panel saying whose listing it is (rule C4).
 *
 * "What the shops say" on its own line; with several shops, an underline tab
 * strip of their names below it, richest first (`detailSources`), that never
 * wraps and scrolls sideways when it does not fit. The tabs are a radio group
 * (one tab stop, arrow keys move between shops) and CSS shows the panel whose
 * radio is checked, so every shop's text is in the server's HTML and the
 * switch works without JavaScript. With one shop there is no strip.
 */
export function Details({ sources }: { sources: DetailSource[] }) {
  if (sources.length === 0) return null;
  const several = sources.length > 1;
  return (
    <section
      data-details
      aria-labelledby="details-heading"
      className="group/details mt-6 min-w-0 lg:mt-5"
    >
      <h2 id="details-heading" className="text-[15px] lg:text-lg">
        What the shops say
      </h2>
      {several ? (
        <>
          <EdgeFade className="mt-2">
            <div
              role="radiogroup"
              aria-labelledby="details-heading"
              data-carousel-track
              className="flex [scrollbar-width:none] overflow-x-auto shadow-[inset_0_-1px_0_var(--line)]"
            >
              {sources.map((source, index) => (
                <Tab key={source.offer.id} source={source} index={index} />
              ))}
            </div>
          </EdgeFade>
          {sources.map((source, index) => (
            <div
              key={source.offer.id}
              data-details-panel={source.label}
              className={cn("hidden", PANEL[index])}
            >
              <Panel source={source} index={index} />
            </div>
          ))}
        </>
      ) : (
        <div data-details-panel={sources[0].label}>
          <Panel source={sources[0]} index={0} />
        </div>
      )}
    </section>
  );
}

function Tab({ source, index }: { source: DetailSource; index: number }) {
  const id = `details-source-${index}`;
  return (
    <>
      <input
        type="radio"
        name="details-source"
        id={id}
        defaultChecked={index === 0}
        className="peer sr-only"
      />
      <label
        htmlFor={id}
        data-details-tab
        className={cn(
          "inline-flex h-11 shrink-0 cursor-pointer items-center border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-ink-2 -outline-offset-2 outline-link hover:text-ink lg:h-10",
          TAB[index],
        )}
      >
        {source.label}
      </label>
    </>
  );
}

function Panel({ source, index }: { source: DetailSource; index: number }) {
  const shop = source.offer.supplier?.name ?? "the shop";
  return (
    <>
      <p data-details-source className="mt-3 text-[13px] text-ink-2">
        From {shop}&apos;s listing
      </p>
      {source.description && <Description text={source.description} />}
      {source.details && <ShopDetails details={source.details} idSuffix={String(index)} />}
    </>
  );
}
