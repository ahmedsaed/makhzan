import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { categoryNameOf, fetchCategories } from "@/lib/api";
import { categoryDescription, pageMetadata, pagedPath } from "@/lib/metadata";
import { joinRef, routes } from "@/lib/routes";
import { totalOf, departmentLabel } from "@/lib/departments";

import { DepartmentBrowse, type RawParams } from "../../_components/department-browse";

/**
 * One category, addressed through its department because category slugs are unique
 * per department only. The department page, narrowed to it.
 */
export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<{ department: string; category: string }>;
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { department, category: slug } = await params;
  const categories = await fetchCategories(department).catch(() => []);
  const category = categories.find((c) => c.slug === slug);
  return pageMetadata({
    // The department disambiguates: "Accessories" is a category in several.
    title: `${category ? categoryNameOf(category) : slug} · ${departmentLabel(department)}`,
    description: category
      ? categoryDescription(category, totalOf(category.ref, categories))
      : undefined,
    path: pagedPath(routes.category(joinRef(department, slug)), await searchParams),
    ownCard: true,
  });
}

export default async function CategoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ department: string; category: string }>;
  searchParams: Promise<RawParams>;
}) {
  const { department, category: slug } = await params;
  const ref = joinRef(department, slug);
  const categories = await fetchCategories(department).catch(() => null);
  // Without the taxonomy there is no telling whether the category exists, so
  // the page degrades to the department's "not answering" state rather than a 404.
  if (!categories) return <DepartmentBrowse department={department} categories={null} params={{}} />;
  const category = categories.find((c) => c.ref === ref);
  if (!category) notFound();

  return (
    <DepartmentBrowse
      department={department}
      categories={categories}
      selected={category}
      params={await searchParams}
    />
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
