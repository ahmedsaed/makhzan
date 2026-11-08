import type { Metadata } from "next";

import { NotAnswering } from "@/components/results";
import { Container, Empty } from "@/components/section";
import { fetchCategories } from "@/lib/api";
import { formatCount, plural } from "@/lib/format";
import { pageMetadata } from "@/lib/metadata";
import { routes } from "@/lib/routes";
import { departmentDirectory } from "@/lib/department-directory";

import { DepartmentDirectory } from "./_components/department-directory";

export async function generateMetadata(): Promise<Metadata> {
  const categories = await fetchCategories().catch(() => null);
  const departments = categories ? departmentDirectory(categories) : [];
  const products = departments.reduce((sum, department) => sum + department.count, 0);
  const names = departments.slice(0, 4).map((department) => department.label);
  return pageMetadata({
    title: "All departments",
    description:
      departments.length > 0
        ? `${plural(departments.length, "department")} and ${plural(products, "product")} from Egypt's suppliers, largest first: ${names.join(", ")} and more, each with its categories and how much each holds.`
        : "Every department makhzan covers, largest first, with its categories and how much each holds.",
    path: routes.departments(),
  });
}

/** Every department as a directory: largest first, each with its categories as links. */
export default async function DepartmentsPage() {
  const categories = await fetchCategories().catch(() => null);
  if (!categories) {
    return (
      <Container className="py-5">
        <h1 className="mb-3 text-2xl">All departments</h1>
        <NotAnswering title="The catalogue is not answering" />
      </Container>
    );
  }
  const departments = departmentDirectory(categories);
  const products = departments.reduce((sum, department) => sum + department.count, 0);
  const listed = departments.reduce((sum, department) => sum + department.categoryCount, 0);

  return (
    <Container className="py-5 md:py-6">
      <div className="mb-3 flex flex-col gap-0.5 md:mb-4 md:flex-row md:items-baseline md:gap-3">
        <h1 className="text-2xl">All {departments.length} departments</h1>
        {departments.length > 0 && (
          <p data-directory-total className="text-[13px] text-ink-3 tabular">
            {formatCount(products)} products in {formatCount(listed)} categories, largest department
            first
          </p>
        )}
      </div>
      {departments.length > 0 ? (
        <DepartmentDirectory departments={departments} />
      ) : (
        <Empty title="No departments yet" hint="The catalogue is empty right now." />
      )}
    </Container>
  );
}

/**
 * Rendered per request, not at build time. The catalogue lives in an API this
 * build has no access to. SSR still gives crawlers complete HTML.
 */
export const dynamic = "force-dynamic";
