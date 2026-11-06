import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Container } from "@/components/section";
import { getCrawlingContent } from "@/lib/content/crawling";
import { isLang } from "@/lib/i18n";

/**
 * The page to point a supplier at when they ask what we are doing. Indexable,
 * and readable even when the catalogue is not: it fetches nothing itself.
 *
 * Rendered per request all the same. It cannot be prerendered while the shared
 * layout's header and footer fetch the catalogue — at build time there is no API
 * to answer them. Making this genuinely static would mean moving those chrome
 * fetches behind a Suspense boundary, which is more surgery than the page is
 * worth today.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string }>;
}): Promise<Metadata> {
  const { lang } = await params;
  if (!isLang(lang)) return {};
  const content = getCrawlingContent(lang);
  return {
    title: content.title,
    description: content.lead,
    alternates: {
      canonical: `/${lang}/how-we-crawl`,
      languages: { en: "/en/how-we-crawl", ar: "/ar/how-we-crawl" },
    },
  };
}

export default async function HowWeCrawlPage({
  params,
}: {
  params: Promise<{ lang: string }>;
}) {
  const { lang } = await params;
  if (!isLang(lang)) notFound();
  const content = getCrawlingContent(lang);

  return (
    <Container className="max-w-2xl py-10">
      <h1 className="text-2xl sm:text-3xl">{content.title}</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-muted">{content.lead}</p>

      <div className="mt-8 flex flex-col gap-7">
        {content.sections.map((section) => (
          <section key={section.heading}>
            <h2 className="font-display text-base font-bold text-ink">{section.heading}</h2>
            {section.body.map((paragraph) => (
              <p key={paragraph} className="mt-2 text-[15px] leading-relaxed text-ink-muted">
                {paragraph}
              </p>
            ))}
          </section>
        ))}

        <section className="rounded-lg border-2 border-rule bg-surface p-4">
          <h2 className="font-display text-base font-bold text-ink">{content.contactHeading}</h2>
          <p className="mt-1 text-[15px] text-ink-muted">{content.contactBody}</p>
          <a
            href={`mailto:${content.contactEmail}`}
            dir="ltr"
            className="mt-1 inline-block font-mono text-sm font-semibold text-accent hover:underline"
          >
            {content.contactEmail}
          </a>
        </section>
      </div>
    </Container>
  );
}

export const dynamic = "force-dynamic";
