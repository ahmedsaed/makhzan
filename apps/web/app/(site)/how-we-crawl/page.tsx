import { Mail } from "lucide-react";
import type { Metadata } from "next";

import { Link } from "@/components/link";
import { Container } from "@/components/section";
import { crawlingContent as content } from "@/lib/content/crawling";
import { routes } from "@/lib/routes";

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
      <p className="mt-3 text-base leading-relaxed text-ink">{content.lead}</p>

      <div className="mt-8 flex flex-col divide-y divide-line border-y border-line">
        {content.sections.map((section) => (
          <section key={section.heading} className="py-5">
            <h2 className="text-lg text-ink">{section.heading}</h2>
            {section.body.map((paragraph) => (
              <p key={paragraph} className="mt-2 text-[15px] leading-relaxed text-ink-2">
                {paragraph}
              </p>
            ))}
          </section>
        ))}
      </div>

      <section className="mt-8 flex flex-col gap-3 rounded-card border border-line bg-surface p-4">
        <div>
          <h2 className="text-base text-ink">{content.contactHeading}</h2>
          <p className="mt-1 text-[15px] leading-relaxed text-ink-2">{content.contactBody}</p>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
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
    </Container>
  );
}

/**
 * Rendered per request, not at build time, so its canonical link resolves
 * against the runtime SITE_URL rather than whatever the build machine had.
 */
export const dynamic = "force-dynamic";
