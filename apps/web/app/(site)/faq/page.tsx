import { ChevronDown } from "lucide-react";
import type { Metadata } from "next";

import { ContentPage, Paragraph } from "@/components/content-page";
import { faqGroups, faqJsonLd, faqLead } from "@/lib/content/faq";
import { pageMetadata } from "@/lib/metadata";
import { jsonLdText } from "@/lib/product";
import { routes } from "@/lib/routes";
import { absoluteUrl } from "@/lib/site";

import { OpenFromHash } from "./open-from-hash";

export const metadata: Metadata = pageMetadata({
  title: "FAQ",
  description:
    "Short answers: buying from the shop, why a price differs, how often prices are checked, listing or removing a shop, and what makhzan keeps.",
  path: routes.faq(),
});

/**
 * Questions people ask, as `<details>`: each opens and closes without
 * JavaScript, and each has an id so it can be linked (`/faq#price-differs`).
 * With JavaScript, a linked question also opens itself (OpenFromHash).
 *
 * Fetches nothing, so it stays up when the catalogue does not. The copy is
 * lib/content/faq.ts.
 */
export default function FaqPage() {
  return (
    <ContentPage title="Questions">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: jsonLdText(faqJsonLd(faqGroups, absoluteUrl(routes.faq()))),
        }}
      />
      <OpenFromHash />
      <Paragraph parts={faqLead} />
      {faqGroups.map((group) => (
        <section key={group.title} aria-labelledby={groupHeadingId(group.title)}>
          <h2
            id={groupHeadingId(group.title)}
            className="mt-7 font-sans text-xs font-semibold tracking-[0.06em] text-ink-3 uppercase"
          >
            {group.title}
          </h2>
          <div className="mt-3 overflow-hidden rounded-card border border-line bg-surface">
            {group.items.map((item) => (
              <details
                key={item.id}
                id={item.id}
                data-faq={item.id}
                className="group scroll-mt-20 border-b border-line last:border-b-0"
              >
                <summary className="flex min-h-[52px] cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5 text-[15px] font-semibold text-ink [&::-webkit-details-marker]:hidden">
                  {item.question}
                  <ChevronDown
                    aria-hidden="true"
                    className="size-[18px] shrink-0 text-ink-3 transition-transform group-open:rotate-180 motion-reduce:transition-none"
                  />
                </summary>
                <div className="px-4 pb-3.5 [&>p:first-child]:mt-0">
                  {item.answer.map((parts, i) => (
                    <Paragraph key={i} parts={parts} />
                  ))}
                </div>
              </details>
            ))}
          </div>
        </section>
      ))}
    </ContentPage>
  );
}

/** The id of a group's heading, which names its section. Prefixed so it can
 *  never take a question's id (questions are linked by theirs). */
function groupHeadingId(title: string) {
  return `faq-group-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

/** Per request, so its canonical link and structured data use the runtime
 *  SITE_URL (as /privacy). */
export const dynamic = "force-dynamic";
