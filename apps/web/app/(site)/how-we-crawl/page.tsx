import { Check, Info, Mail, Minus, TriangleAlert, X } from "lucide-react";
import type { Metadata } from "next";

import { Link } from "@/components/link";
import { Container } from "@/components/section";
import { fetchCrawlerActivity } from "@/lib/api";
import { CONTENTS, crawlingContent as content, SECTION, SITE } from "@/lib/content/crawling";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import { siteUrl } from "@/lib/site";
import { cn } from "@/lib/utils";

import { CrawlerActivitySection } from "./activity";
import { Contents, Snippet, Tabs } from "./enhance";

/**
 * The page to point a supplier at when they ask what we are doing. Indexable,
 * and readable even when the catalogue is not: its one fetch, the crawler's
 * activity, fails soft — the policy renders without it, and the section says
 * the figures can't be shown.
 *
 * Server-rendered and whole without JavaScript: the identification tabs are
 * then three panels one after another, and the copy buttons are absent.
 */
export const metadata: Metadata = pageMetadata({
  title: content.title,
  description: content.lead,
  path: routes.howWeCrawl(),
});

export default async function HowWeCrawlPage() {
  const activity = await fetchCrawlerActivity();
  // The copy names our own origin (the User-Agent, the key directory) as SITE;
  // it is filled in here from SITE_URL so one image serves any host.
  const origin = siteUrl().origin;
  const withSite = (text: string) => text.replaceAll(SITE, origin);

  return (
    <Container className="py-7 pb-16">
      <div
        id="top"
        className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[13rem_minmax(0,48rem)] lg:justify-center lg:gap-12"
      >
        <Contents items={CONTENTS} />

        <div className="min-w-0">
          <Hero />
          <WhatWeRead />
          <Recognise withSite={withSite} />
          <Robots />
          <Pace />
          <Keep />
          <CrawlerActivitySection activity={activity} content={content.activity} now={new Date()} />
          <Suppliers />
          <Questions />
          <Contact />
        </div>
      </div>
    </Container>
  );
}

/* ------------------------------------------------------------------------ */
/* Building blocks                                                          */
/* ------------------------------------------------------------------------ */

function Section({
  id,
  heading,
  lead,
  children,
}: {
  id: string;
  heading: string;
  lead?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className="scroll-mt-[72px] pt-9 lg:scroll-mt-6"
    >
      <h2 id={`${id}-heading`} className="text-[22px] text-ink">
        {heading}
      </h2>
      {lead && <p className="mt-1.5 mb-4 max-w-2xl text-[15px] text-ink-2">{lead}</p>}
      {children}
    </section>
  );
}

function Card({
  className,
  id,
  children,
}: {
  className?: string;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <div id={id} className={cn("rounded-card border border-line bg-surface p-4", className)}>
      {children}
    </div>
  );
}

function Kicker({
  children,
  className,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <p
      id={id}
      className={cn("mb-1.5 text-xs font-semibold tracking-wider text-ink-3 uppercase", className)}
    >
      {children}
    </p>
  );
}

/** A round mark before a list heading: a tick for what we do, a cross for what we don't. */
function Mark({ kind }: { kind: "yes" | "no" | "info" | "end" }) {
  const Icon = { yes: Check, no: X, info: Info, end: Minus }[kind];
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-grid size-[22px] shrink-0 place-items-center rounded-full",
        kind === "yes"
          ? "bg-badge text-badge-ink"
          : "border border-line-strong bg-ground text-ink-2",
      )}
    >
      <Icon className="size-3.5" strokeWidth={2.5} />
    </span>
  );
}

function DoList({
  kind,
  heading,
  children,
}: {
  kind: "yes" | "no";
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <h3 className="mb-2.5 flex items-center gap-2 text-base text-ink">
        <Mark kind={kind} />
        {heading}
      </h3>
      <ul className="flex flex-col gap-2.5 text-[14.5px] leading-normal text-ink-2">{children}</ul>
    </Card>
  );
}

function Item({ children }: { children: React.ReactNode }) {
  return <li className="pl-[30px]">{children}</li>;
}

/** A numbered marker tying a line of the example request to its note. */
function Marker({ n }: { n: number }) {
  return (
    <span
      aria-hidden="true"
      className="mr-1 inline-grid size-[18px] place-items-center rounded-full bg-action align-[1px] font-sans text-[11px] font-semibold text-action-ink"
    >
      {n}
    </span>
  );
}

/* ------------------------------------------------------------------------ */
/* Sections                                                                 */
/* ------------------------------------------------------------------------ */

function Hero() {
  return (
    <div>
      <h1 className="text-[clamp(28px,5vw,36px)] leading-tight">{content.title}</h1>
      <p className="mt-2.5 max-w-[40rem] text-[17px] leading-relaxed text-ink">{content.lead}</p>

      <ul aria-label="At a glance" className="mt-5 grid grid-cols-2 gap-2 md:grid-cols-4">
        {content.glance.map((tile) => (
          <li key={tile.label}>
            <a
              href={tile.href}
              className="flex h-full min-h-11 flex-col gap-0.5 rounded-card border border-line bg-surface p-3 hover:border-line-strong"
            >
              <span className="text-xs text-ink-2">{tile.label}</span>
              <span
                className={cn(
                  "leading-tight text-ink",
                  tile.mono ? "font-mono text-base font-medium" : "figure text-[17px]",
                )}
              >
                {tile.value}
              </span>
              <span className="mt-0.5 text-[12.5px] leading-snug text-ink-2">{tile.note}</span>
            </a>
          </li>
        ))}
      </ul>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-ink-2">
        <span>robots.txt read first, and obeyed</span>
        {content.glanceLinks.map((link) => (
          <a
            key={link.href}
            href={link.href}
            className="inline-flex min-h-11 items-center font-semibold text-link hover:underline md:min-h-0"
          >
            {link.label} →
          </a>
        ))}
      </div>
    </div>
  );
}

function WhatWeRead() {
  const { read } = content;
  return (
    <Section id={SECTION.read} heading={read.heading} lead={read.lead}>
      <div className="grid gap-3 sm:grid-cols-2">
        <DoList kind="yes" heading="We read">
          <Item>{read.weRead}</Item>
        </DoList>
        <DoList kind="no" heading="We do not">
          {read.weDoNot.map((line) => (
            <Item key={line}>{line}</Item>
          ))}
        </DoList>
      </div>
    </Section>
  );
}

function Recognise({ withSite }: { withSite: (text: string) => string }) {
  const { verify } = content;
  const { request, notes, tabs } = verify;
  const noteItems = [
    { n: 1, ...notes.userAgent },
    { n: 2, ...notes.from },
    { n: 3, ...notes.signature },
  ];
  return (
    <Section id={SECTION.verify} heading={verify.heading} lead={verify.lead}>
      <Kicker id="example-request">{verify.requestLabel}</Kicker>
      <figure
        aria-labelledby="example-request"
        className="m-0 grid gap-3 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]"
      >
        <pre
          data-example-request
          className="rounded-card border border-line bg-ground p-3 font-mono text-[12.5px] leading-[1.65] break-all whitespace-pre-wrap text-ink-2"
        >
          <span className="text-ink-3">{request.start}</span>
          {"\n"}
          <Marker n={1} />
          <span className="text-ink">{withSite(request.userAgent)}</span>
          {"\n"}
          <Marker n={2} />
          <span className="text-ink">{request.from}</span>
          {request.signature.map((line, i) => (
            <span key={line}>
              {"\n"}
              <Marker n={3} />
              <span className={i === 0 ? "text-ink" : undefined}>{withSite(line)}</span>
            </span>
          ))}
        </pre>
        <ol className="flex flex-col gap-3 text-sm text-ink-2">
          {noteItems.map((note) => (
            <li key={note.n} className="grid grid-cols-[22px_minmax(0,1fr)] gap-1.5">
              <Marker n={note.n} />
              <span>
                <b className="font-semibold text-ink">{note.title}</b> {note.body}
              </span>
            </li>
          ))}
        </ol>
      </figure>

      <Tabs
        label={verify.tabsLabel}
        panels={[
          {
            id: "user-agent",
            label: tabs.userAgent.label,
            content: (
              <div className="text-[15px] text-ink-2">
                <p>{tabs.userAgent.lead}</p>
                <Snippet text={withSite(tabs.userAgent.snippet)} name="User-Agent" />
                <p className="mt-2.5">{tabs.userAgent.notMoved}</p>
              </div>
            ),
          },
          {
            id: "robots-token",
            label: tabs.robots.label,
            content: (
              <div className="text-[15px] text-ink-2">
                <p>{tabs.robots.body}</p>
                <Snippet text={tabs.robots.snippet} name="robots.txt token" />
                <p className="mt-2.5">
                  <a
                    href={tabs.robots.more.href}
                    className="font-semibold text-link hover:underline"
                  >
                    {tabs.robots.more.label} →
                  </a>
                </p>
              </div>
            ),
          },
          {
            id: "web-bot-auth",
            label: tabs.signature.label,
            content: (
              <div className="text-[15px] text-ink-2">
                <p>{tabs.signature.body}</p>
                <p className="mt-2.5">{tabs.signature.keyLead}</p>
                <Snippet text={withSite(tabs.signature.snippet)} name="key directory URL" />
              </div>
            ),
          },
        ]}
      />

      <div className="mt-3.5 grid grid-cols-[22px_minmax(0,1fr)] items-start gap-2.5 rounded-card border border-line bg-surface px-3.5 py-3 text-[14.5px]">
        <Mark kind="info" />
        <b className="font-semibold text-ink">{verify.noAddresses}</b>
      </div>
    </Section>
  );
}

function Robots() {
  const { robots } = content;
  return (
    <Section id={SECTION.robots} heading={robots.heading} lead={robots.lead}>
      <ol className="grid gap-2 md:grid-cols-4">
        {robots.steps.map((step, i) => (
          <li key={step.title} className="rounded-card border border-line bg-surface p-3">
            <span
              aria-hidden="true"
              className={cn(
                "mb-1.5 inline-grid size-[22px] place-items-center rounded-full text-xs font-semibold",
                step.alt
                  ? "border border-line-strong bg-ground text-ink-2"
                  : "bg-chip-on text-chip-on-ink",
              )}
            >
              {i + 1}
            </span>
            <span className="block text-[11.5px] font-semibold tracking-wide text-ink-3 uppercase">
              {step.tag}
            </span>
            <b className="block text-[14.5px] font-semibold text-ink">{step.title}</b>
            {step.body && (
              <span className="mt-0.5 block text-[13.5px] leading-snug text-ink-2">
                {step.body}
              </span>
            )}
          </li>
        ))}
      </ol>

      <Card className="mt-3">
        <h3 className="text-base text-ink">{robots.delayHeading}</h3>
        <p className="mt-1 text-[14.5px] text-ink-2">{robots.delayBody}</p>
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
          <DelayBar label={robots.delayOurs} value="at least 15 s" fill="75%" />
          <DelayBar
            label={
              <>
                {robots.delayShop} <code className="font-mono">Crawl-delay: 20</code>
              </>
            }
            value="20 s"
            fill="100%"
            on
          />
        </div>
      </Card>

      <Card id={SECTION.block} className="mt-3 scroll-mt-[72px] lg:scroll-mt-6">
        <h3 className="text-base text-ink">{robots.blockHeading}</h3>
        <p className="mt-1 text-[14.5px] text-ink-2">{robots.blockLead}</p>
        <Snippet text={robots.block} name="robots.txt block" />
      </Card>
    </Section>
  );
}

function DelayBar({
  label,
  value,
  fill,
  on = false,
}: {
  label: React.ReactNode;
  value: string;
  fill: string;
  on?: boolean;
}) {
  return (
    <div>
      <span className="text-[13px] text-ink-2">{label}</span>
      <div
        aria-hidden="true"
        className="mt-2 h-2.5 overflow-hidden rounded-full border border-line bg-ground"
      >
        <i className={cn("block h-full", on ? "bg-action" : "bg-ink-3")} style={{ width: fill }} />
      </div>
      <span className="figure text-sm text-ink">{value}</span>
    </div>
  );
}

function Pace() {
  const { pace } = content;
  const gaps = [95, 245, 395, 545];
  return (
    <Section id={SECTION.pace} heading={pace.heading} lead={pace.lead}>
      <Card>
        <Kicker>{pace.trackLabel}</Kicker>
        <svg viewBox="0 0 640 64" aria-hidden="true" className="mt-1 block h-auto w-full">
          <line x1="8" y1="26" x2="632" y2="26" className="stroke-line-strong" strokeWidth="2" />
          {[20, 170, 320, 470, 620].map((cx) => (
            <circle key={cx} cx={cx} cy="26" r="7" className="fill-action" />
          ))}
          {gaps.map((x) => (
            <text
              key={x}
              x={x}
              y="56"
              textAnchor="middle"
              className="fill-ink-2 font-sans text-[14px]"
            >
              ≥ 15 s
            </text>
          ))}
        </svg>

        <Kicker className="mt-4.5">{pace.cycleLabel}</Kicker>
        <div role="img" aria-label={pace.cycleAlt} className="mt-3 grid grid-cols-7 gap-1">
          {Array.from({ length: 7 }, (_, i) => (
            <div key={i} className="flex min-w-0 flex-col gap-1">
              <b className="text-center text-xs font-semibold text-ink">
                {i === 0 ? "Day 1" : i === 6 ? "≈7" : i + 1}
              </b>
              <div className="relative h-11 overflow-hidden rounded-md border border-line bg-badge">
                <i className="absolute inset-0 bg-action/85" />
              </div>
              <small className="text-center text-[11.5px] leading-tight text-ink-3">
                {i === 0 ? "03:00 UTC" : "03:00"}
              </small>
            </div>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap justify-between gap-x-3 gap-y-1 text-[13px] text-ink-2">
          <span>{pace.cycleDay}</span>
          <span>{pace.cycleWeek}</span>
        </div>
        <p className="mt-2.5 text-[14.5px] text-ink-2">{pace.cycleBody}</p>
        <div className="mt-3 grid grid-cols-[22px_minmax(0,1fr)] gap-2 border-t border-dashed border-line-strong pt-3 text-sm text-ink-2">
          <Mark kind="end" />
          <span>
            <b className="font-semibold text-ink">At the end of a pass:</b> {pace.endOfPass}
          </span>
        </div>
      </Card>

      <Card className="mt-3">
        <h3 className="mb-2.5 text-base text-ink">{pace.pushbackHeading}</h3>
        <ul className="flex flex-col">
          {pace.pushback.map((row) => (
            <li
              key={row.when}
              className="grid gap-x-4 gap-y-0.5 border-t border-line py-3 first:border-t-0 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]"
            >
              <span className="text-sm text-ink-2">{row.when}</span>
              <span className="text-[14.5px] font-medium text-ink">{row.then}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="mt-3">
        <h3 className="text-base text-ink">{pace.hourHeading}</h3>
        <p className="mt-1 text-[14.5px] text-ink-2">
          {pace.hourBody}{" "}
          <a href={pace.hourAsk.href} className="font-semibold text-link hover:underline">
            {pace.hourAsk.label} →
          </a>
        </p>
      </Card>
    </Section>
  );
}

function Keep() {
  const { keep } = content;
  return (
    <Section id={SECTION.keep} heading={keep.heading} lead={keep.lead}>
      <div className="grid gap-3 sm:grid-cols-2">
        <DoList kind="yes" heading={keep.keepHeading}>
          {keep.kept.map(({ item, note }) => (
            <li key={item} className="pl-[30px] text-ink">
              {item}
              {note && <small className="block text-[13px] text-ink-2">{note}</small>}
            </li>
          ))}
        </DoList>
        <DoList kind="no" heading={keep.dontHeading}>
          {keep.dont.map((line) => (
            <Item key={line}>{line}</Item>
          ))}
        </DoList>
      </div>
      <p className="mt-3 text-[14.5px] text-ink-2">{keep.readers}</p>
      <div
        id={SECTION.prices}
        className="mt-3.5 grid scroll-mt-[72px] grid-cols-[22px_minmax(0,1fr)] items-start gap-2.5 rounded-card border border-warn-line bg-warn px-3.5 py-3 text-[14.5px] text-warn-ink lg:scroll-mt-6"
      >
        <TriangleAlert aria-hidden="true" className="mt-0.5 size-5" />
        <span>
          <b className="font-semibold">{keep.pricesTitle}</b> {keep.pricesBody}
        </span>
      </div>
    </Section>
  );
}

function Suppliers() {
  const { suppliers } = content;
  return (
    <Section id={SECTION.suppliers} heading={suppliers.heading} lead={suppliers.lead}>
      <div className="grid gap-2.5 sm:grid-cols-2">
        {suppliers.cards.map((card) => (
          <Card key={card.heading}>
            <h3 className="mb-1.5 text-[15.5px] text-ink">{card.heading}</h3>
            <p className="text-[14.5px] text-ink-2">{card.body}</p>
          </Card>
        ))}
      </div>
    </Section>
  );
}

function Questions() {
  const { faq } = content;
  return (
    <Section id={SECTION.faq} heading={faq.heading} lead={faq.lead}>
      <div className="divide-y divide-line rounded-card border border-line bg-surface">
        {faq.items.map((item) => (
          <details key={item.question} className="group">
            <summary className="flex min-h-[52px] cursor-pointer list-none items-center justify-between gap-3 px-4 py-2 font-semibold text-ink [&::-webkit-details-marker]:hidden">
              {item.question}
              <span
                aria-hidden="true"
                className="-mt-1 size-[9px] shrink-0 rotate-45 border-r-2 border-b-2 border-ink-2 transition-transform group-open:mt-1 group-open:-rotate-135"
              />
            </summary>
            <p className="px-4 pb-3.5 text-[14.5px] text-ink-2">
              {item.answer}{" "}
              <a href={item.more.href} className="font-semibold text-link hover:underline">
                {item.more.label} →
              </a>
            </p>
          </details>
        ))}
      </div>
    </Section>
  );
}

function Contact() {
  return (
    <section
      id={SECTION.contact}
      aria-labelledby="contact-heading"
      className="mt-9 scroll-mt-[72px] rounded-card border border-line bg-surface p-4 lg:scroll-mt-6"
    >
      <h2 id="contact-heading" className="text-[17px] text-ink">
        {content.contactHeading}
      </h2>
      <p className="mt-1 text-[15px] text-ink-2">{content.contactBody}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1">
        <a
          href={`mailto:${content.contactEmail}`}
          className="inline-flex h-11 items-center gap-2 font-semibold text-link hover:underline"
        >
          <Mail aria-hidden="true" className="size-4" />
          {content.contactEmail}
        </a>
        <Link
          href={routes.forSuppliers()}
          className="inline-flex h-11 items-center text-sm text-ink-2 hover:text-ink hover:underline"
        >
          Remove, add or correct a shop
        </Link>
      </div>
    </section>
  );
}

/**
 * Rendered per request, not at build time, so its canonical link resolves
 * against the runtime SITE_URL rather than whatever the build machine had.
 */
export const dynamic = "force-dynamic";
