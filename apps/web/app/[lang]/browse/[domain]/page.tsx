import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { labelFor } from "@/components/browse-menu";
import { CategoryTiles } from "@/components/category-tile";
import { Container, SectionHeading } from "@/components/section";
import { fetchCategories } from "@/lib/api";
import { getDictionary, isLang, localeOf } from "@/lib/i18n";

/**
 * One page per vertical — the first surface that uses `?domain=`. It answers
 * "what does makhzan have in this trade" with the category tree and its counts.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string; domain: string }>;
}): Promise<Metadata> {
  const { lang, domain } = await params;
  if (!isLang(lang)) return {};
  return { title: labelFor(domain, lang) };
}

export default async function VerticalPage({
  params,
}: {
  params: Promise<{ lang: string; domain: string }>;
}) {
  const { lang, domain } = await params;
  if (!isLang(lang)) notFound();
  const t = getDictionary(lang);
  const locale = localeOf(lang);

  const categories = await fetchCategories(domain);
  // An unknown domain has no categories — that is a 404, not an empty page.
  if (categories.length === 0) notFound();

  const byRef = new Map(categories.map((category) => [category.ref, category]));
  // Leaves hold the products; parents are browse groups and become the eyebrow.
  const leaves = categories
    .filter((category) => !categories.some((other) => other.parent === category.ref))
    .sort((a, b) => b.count - a.count);

  const total = categories.reduce((sum, category) => sum + category.count, 0);

  return (
    <Container className="py-8">
      <p className="text-xs text-ink-muted">
        <span data-numeric className="font-mono">
          {total.toLocaleString(locale)}
        </span>{" "}
        {t.statProducts}
      </p>
      <h1 className="mt-1 mb-5 text-2xl">{labelFor(domain, lang)}</h1>
      <SectionHeading>{t.facetCategory}</SectionHeading>
      <CategoryTiles
        categories={leaves}
        lang={lang}
        eyebrowOf={(category) => {
          const parent = category.parent ? byRef.get(category.parent) : undefined;
          if (!parent) return null;
          return (lang === "ar" && parent.name_ar) || parent.name_en;
        }}
      />
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to, and prerendering 57,000 products would be pointless
 * anyway. SSR still gives crawlers complete HTML — the caching that matters
 * happens in the fetch layer (see lib/api.ts), not in the page shell.
 */
export const dynamic = "force-dynamic";
