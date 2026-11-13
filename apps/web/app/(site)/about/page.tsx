import type { Metadata } from "next";

import { ContentPage, ContentSection, Paragraph } from "@/components/content-page";
import { Link } from "@/components/link";
import { fetchCategories, fetchStats } from "@/lib/api";
import { aboutLead, aboutSections, catalogueLine, type AboutSection } from "@/lib/content/about";
import { departmentsFrom } from "@/lib/departments";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";

export const metadata: Metadata = pageMetadata({
  title: "About",
  description:
    "makhzan is a free directory of Egyptian hardware and electronics shops: one search across their public catalogues, then you buy from the shop. No ads, and no shop pays to appear.",
  path: routes.about(),
});

/**
 * What makhzan is, for a visitor who wonders. The copy is lib/content/about.ts.
 *
 * Its one fetch is the catalogue's size, and it fails soft: with the API down
 * the line falls back to words and the rest of the page is unchanged. Both
 * reads go through lib/api.ts's data cache (five minutes, like the home
 * page's totals), so a busy About page asks the API at most once in five
 * minutes, though the page itself renders per request for its canonical link.
 */
export default async function AboutPage() {
  const [stats, categories] = await Promise.all([
    fetchStats().catch(() => null),
    fetchCategories().catch(() => null),
  ]);
  const departments = categories
    ? departmentsFrom(categories).filter((department) => department.count > 0).length
    : null;

  return (
    <ContentPage title="About makhzan">
      <Paragraph parts={[aboutLead]} />
      <p data-catalogue-size className="mt-3 text-[15px] leading-relaxed text-ink-2">
        {catalogueLine(stats, departments)}
      </p>
      {aboutSections.map((section) => (
        <ContentSection key={section.id} id={section.id} title={section.title}>
          <Body section={section} />
        </ContentSection>
      ))}
    </ContentPage>
  );
}

function Body({ section }: { section: AboutSection }) {
  return (
    <>
      {section.before?.map((parts, i) => (
        <Paragraph key={i} parts={parts} />
      ))}
      {section.steps && (
        <ol className="mt-4 overflow-hidden rounded-card border border-line bg-surface">
          {section.steps.map((step, i) => (
            <li
              key={step.title}
              className="flex gap-3 border-b border-line px-4 py-3.5 last:border-b-0"
            >
              <span
                aria-hidden="true"
                className="grid size-7 shrink-0 place-items-center rounded-full bg-chip-on font-display text-sm font-bold text-chip-on-ink"
              >
                {i + 1}
              </span>
              <div className="min-w-0">
                <h3 className="font-sans text-[15px] font-semibold tracking-normal text-ink">
                  {step.title}
                </h3>
                <p className="mt-0.5 text-sm leading-relaxed text-ink-2">
                  {step.body}
                  {step.more && (
                    <>
                      {" "}
                      <Link
                        href={step.more.href}
                        className="font-semibold text-link hover:underline"
                      >
                        {step.more.label}
                      </Link>
                    </>
                  )}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
      {section.callout && (
        <div className="mt-4 rounded-card border border-line-strong bg-surface px-4 py-3.5">
          <p className="font-medium text-ink">{section.callout}</p>
        </div>
      )}
      {section.after?.map((parts, i) => (
        <Paragraph key={i} parts={parts} />
      ))}
      {section.more && (
        <p className="mt-1 flex flex-wrap items-center gap-x-3">
          {section.more.map((link, i) => (
            <span key={link.href} className="contents">
              {i > 0 && (
                <span aria-hidden="true" className="text-ink-3">
                  ·
                </span>
              )}
              <Link
                href={link.href}
                className="inline-flex h-11 items-center text-sm font-semibold text-link hover:underline"
              >
                {link.label}
              </Link>
            </span>
          ))}
        </p>
      )}
    </>
  );
}

/** Per request, so its canonical link uses the runtime SITE_URL (as /privacy).
 *  The totals behind it are cached by lib/api.ts. */
export const dynamic = "force-dynamic";
