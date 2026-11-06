import type { DetailSource } from "@/lib/product";
import { cn } from "@/lib/utils";

import { Description } from "./description";
import { ShopDetails } from "./shop-details";

/*
 * Tailwind only generates classes it can read in the source, so each tab's
 * named peer is spelled out. Named peers matter: with one shared `peer`, the
 * first checked radio would also reveal every panel after it.
 */
const PEER = [
  "peer/s0",
  "peer/s1",
  "peer/s2",
  "peer/s3",
  "peer/s4",
  "peer/s5",
  "peer/s6",
  "peer/s7",
];
const PANEL = [
  "peer-checked/s0:block",
  "peer-checked/s1:block",
  "peer-checked/s2:block",
  "peer-checked/s3:block",
  "peer-checked/s4:block",
  "peer-checked/s5:block",
  "peer-checked/s6:block",
  "peer-checked/s7:block",
];
const TAB = [
  "peer-checked/s0:bg-chip-on peer-checked/s0:text-chip-on-ink peer-checked/s0:border-chip-on peer-focus-visible/s0:outline-2",
  "peer-checked/s1:bg-chip-on peer-checked/s1:text-chip-on-ink peer-checked/s1:border-chip-on peer-focus-visible/s1:outline-2",
  "peer-checked/s2:bg-chip-on peer-checked/s2:text-chip-on-ink peer-checked/s2:border-chip-on peer-focus-visible/s2:outline-2",
  "peer-checked/s3:bg-chip-on peer-checked/s3:text-chip-on-ink peer-checked/s3:border-chip-on peer-focus-visible/s3:outline-2",
  "peer-checked/s4:bg-chip-on peer-checked/s4:text-chip-on-ink peer-checked/s4:border-chip-on peer-focus-visible/s4:outline-2",
  "peer-checked/s5:bg-chip-on peer-checked/s5:text-chip-on-ink peer-checked/s5:border-chip-on peer-focus-visible/s5:outline-2",
  "peer-checked/s6:bg-chip-on peer-checked/s6:text-chip-on-ink peer-checked/s6:border-chip-on peer-focus-visible/s6:outline-2",
  "peer-checked/s7:bg-chip-on peer-checked/s7:text-chip-on-ink peer-checked/s7:border-chip-on peer-focus-visible/s7:outline-2",
];

/**
 * What the shops wrote about the product: description, specs and datasheets,
 * one shop at a time (rule C4: each labelled with its source).
 *
 * With several shops, a "From:" row of tabs switches between them. They are
 * radio buttons, and CSS shows the panel whose radio is checked, so every
 * shop's text is in the server's HTML and the switch works without
 * JavaScript. Opens on the richest shop (`detailSources`).
 */
export function Details({ sources, single }: { sources: DetailSource[]; single: boolean }) {
  if (sources.length === 0) return null;
  if (sources.length === 1) {
    return (
      <div data-details className="min-w-0">
        <Panel source={sources[0]} index={0} single={single} />
      </div>
    );
  }
  return (
    <section data-details aria-labelledby="details-heading" className="mt-6 min-w-0 lg:mt-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
        <h2 id="details-heading" className="me-1 text-[15px] lg:text-lg">
          Details
        </h2>
        <span className="text-[13px] text-ink-2">From</span>
        {/* The radios and labels come first, in one wrapping row; each panel
            follows as a full-width item, and only the checked one shows. They
            must stay siblings: the CSS reaches a panel from its radio with
            `~`. One name makes them one group for screen readers too. */}
        {sources.map((source, index) => (
          <Tab key={source.offer.id} source={source} index={index} />
        ))}
        {sources.map((source, index) => (
          <div
            key={source.offer.id}
            data-details-panel={source.label}
            className={cn("order-last hidden w-full basis-full", PANEL[index])}
          >
            <Panel source={source} index={index} single={false} />
          </div>
        ))}
      </div>
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
        className={cn("sr-only", PEER[index])}
      />
      <label
        htmlFor={id}
        data-details-tab
        className={cn(
          "inline-flex h-11 cursor-pointer items-center rounded-full border border-line-strong bg-surface px-3.5 text-sm font-medium text-ink-2 outline-offset-2 outline-link lg:h-9",
          TAB[index],
        )}
      >
        {source.label}
      </label>
    </>
  );
}

function Panel({
  source,
  index,
  single,
}: {
  source: DetailSource;
  index: number;
  single: boolean;
}) {
  const shop = source.offer.supplier?.name ?? "the shop";
  return (
    <>
      {source.description && (
        <Description
          heading={single ? "From the shop's description" : `From ${shop}'s description`}
          text={source.description}
        />
      )}
      {source.details && <ShopDetails details={source.details} idSuffix={String(index)} />}
    </>
  );
}
