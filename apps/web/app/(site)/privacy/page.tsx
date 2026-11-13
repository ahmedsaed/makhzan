import type { Metadata } from "next";

import { Container } from "@/components/section";
import { CONTACT_EMAIL } from "@/lib/content/crawling";
import {
  PRIVACY_UPDATED,
  privacyLead,
  privacySections,
  type PrivacyBlock,
} from "@/lib/content/privacy";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";

export const metadata: Metadata = pageMetadata({
  title: "Privacy",
  description:
    "What makhzan keeps about you, why, and for how long. No account, no cookies; a report's email is deleted 90 days after it is sent.",
  path: routes.privacy(),
});

/**
 * What makhzan keeps about visitors, why and for how long (Egypt's PDPL, Law
 * 151 of 2020). It shipped before the "Report a problem" form that links to
 * it, as the owner required. The copy is lib/content/privacy.ts.
 *
 * Fetches nothing, so it stays up when the catalogue does not.
 */
export default function PrivacyPage() {
  return (
    <Container className="max-w-2xl py-10">
      <h1 className="text-2xl sm:text-3xl">Privacy</h1>
      <p className="mt-1 text-sm text-ink-2">Last updated {PRIVACY_UPDATED}</p>
      {privacyLead.map((text) => (
        <p key={text} className="mt-3 text-[15px] leading-relaxed text-ink-2">
          {text}
        </p>
      ))}
      {privacySections.map((section) => (
        <section
          key={section.id}
          id={section.id}
          aria-labelledby={`${section.id}-heading`}
          className="mt-8 scroll-mt-20"
        >
          <h2 id={`${section.id}-heading`} className="text-lg text-ink">
            {section.title}
          </h2>
          {section.blocks.map((block, i) => (
            <Block key={i} block={block} />
          ))}
        </section>
      ))}
    </Container>
  );
}

/** A paragraph, with the contact address made a link wherever it appears. */
function Prose({ text }: { text: string }) {
  const [before, ...rest] = text.split(CONTACT_EMAIL);
  if (rest.length === 0) return <>{text}</>;
  return (
    <>
      {before}
      {rest.map((after, i) => (
        <span key={i}>
          <a href={`mailto:${CONTACT_EMAIL}`} className="font-semibold text-link hover:underline">
            {CONTACT_EMAIL}
          </a>
          {after}
        </span>
      ))}
    </>
  );
}

function Block({ block }: { block: PrivacyBlock }) {
  if (block.kind === "p") {
    return (
      <p className="mt-3 text-[15px] leading-relaxed text-ink-2">
        <Prose text={block.text} />
      </p>
    );
  }
  if (block.kind === "list") {
    return (
      <ul className="mt-3 flex list-disc flex-col gap-1.5 ps-5 text-[15px] leading-relaxed text-ink-2">
        {block.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    );
  }
  // A table on wide screens; on a phone each row is a block of its own, so
  // nothing scrolls sideways (S4).
  return (
    <dl
      data-retention
      className="mt-4 overflow-hidden rounded-card border border-line bg-surface text-[15px]"
    >
      {block.rows.map((row) => (
        <div
          key={row.what}
          className="grid gap-1 border-b border-line px-3.5 py-3 last:border-b-0 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] sm:gap-4"
        >
          <dt className="font-semibold text-ink">{row.what}</dt>
          <dd className="leading-relaxed text-ink-2">{row.kept}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Per request, so its canonical link uses the runtime SITE_URL (as /for-suppliers). */
export const dynamic = "force-dynamic";
