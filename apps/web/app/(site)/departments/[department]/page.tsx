import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { fetchCategories } from "@/lib/api";
import { pageMetadata, departmentDescription, pagedPath } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import { departmentLabel } from "@/lib/departments";

import { DepartmentBrowse, type RawParams } from "../_components/department-browse";

export async function generateMetadata({
  params,
  searchParams,
}: {
  params: Promise<{ department: string }>;
  searchParams: Promise<RawParams>;
}): Promise<Metadata> {
  const { department } = await params;
  const categories = await fetchCategories(department).catch(() => []);
  return pageMetadata({
    title: departmentLabel(department),
    description: departmentDescription(department, categories),
    path: pagedPath(routes.department(department), await searchParams),
    ownCard: true,
  });
}

/** One department: its groups, its biggest categories, and its products. */
export default async function DepartmentPage({
  params,
  searchParams,
}: {
  params: Promise<{ department: string }>;
  searchParams: Promise<RawParams>;
}) {
  const { department } = await params;
  // A failed fetch is not an unknown department: the page says the catalogue is not
  // answering instead of claiming the department does not exist.
  const categories = await fetchCategories(department).catch(() => null);
  // An unknown department has no categories — that is a 404, not an empty page.
  if (categories?.length === 0) notFound();

  return <DepartmentBrowse department={department} categories={categories} params={await searchParams} />;
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
