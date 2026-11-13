import type { Metadata } from "next";

import { ContentPage, ContentSection, Paragraph } from "@/components/content-page";
import { Prose } from "@/components/prose";
import { TERMS_UPDATED, termsLead, termsSections, type TermsBlock } from "@/lib/content/terms";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";

export const metadata: Metadata = pageMetadata({
  title: "Terms of use",
  description:
    "The terms for using makhzan: what it is, that its information can be out of date, that buying is between you and the shop, and how to use it fairly.",
  path: routes.terms(),
});

/**
 * The terms of use, short and plain, laid out as /privacy. The copy is
 * lib/content/terms.ts. Fetches nothing.
 */
export default function TermsPage() {
  return (
    <ContentPage title="Terms of use">
      <p className="mt-1 text-sm text-ink-2">Last updated {TERMS_UPDATED}</p>
      <Paragraph parts={termsLead} />
      {termsSections.map((section) => (
        <ContentSection key={section.id} id={section.id} title={section.title}>
          {section.blocks.map((block, i) => (
            <Block key={i} block={block} />
          ))}
        </ContentSection>
      ))}
    </ContentPage>
  );
}

function Block({ block }: { block: TermsBlock }) {
  if (block.kind === "p") return <Paragraph parts={block.text} />;
  return (
    <ul className="mt-3 flex list-disc flex-col gap-1.5 ps-5 text-[15px] leading-relaxed text-ink-2">
      {block.items.map((item, i) => (
        <li key={i}>
          <Prose parts={item} />
        </li>
      ))}
    </ul>
  );
}

/** Per request, so its canonical link uses the runtime SITE_URL (as /privacy). */
export const dynamic = "force-dynamic";
