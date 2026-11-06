import type { Metadata } from "next";

import { Container } from "@/components/section";
import { crawlingContent as content } from "@/lib/content/crawling";

/**
 * The page to point a supplier at when they ask what we are doing. Indexable,
 * and readable even when the catalogue is not: it fetches nothing, and neither
 * does the chrome around it, so it is prerendered at build time.
 */
export const metadata: Metadata = {
  title: content.title,
  description: content.lead,
  alternates: { canonical: "/how-we-crawl" },
};

export default function HowWeCrawlPage() {
  return (
    <Container className="max-w-2xl py-10">
      <h1 className="text-2xl sm:text-3xl">{content.title}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{content.lead}</p>

      <div className="mt-8 flex flex-col gap-7">
        {content.sections.map((section) => (
          <section key={section.heading}>
            <h2 className="text-base text-ink">{section.heading}</h2>
            {section.body.map((paragraph) => (
              <p key={paragraph} className="mt-2 text-[15px] leading-relaxed text-ink-2">
                {paragraph}
              </p>
            ))}
          </section>
        ))}

        <section className="rounded-card border border-line bg-surface p-4">
          <h2 className="text-base text-ink">{content.contactHeading}</h2>
          <p className="mt-1 text-[15px] text-ink-2">{content.contactBody}</p>
          <a
            href={`mailto:${content.contactEmail}`}
            className="mt-1 inline-block text-sm font-semibold text-link hover:underline"
          >
            {content.contactEmail}
          </a>
        </section>
      </div>
    </Container>
  );
}
