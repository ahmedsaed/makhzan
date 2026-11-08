import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { DepartmentIcon } from "@/components/department-icon";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { asPhrase, type DepartmentSummary } from "@/lib/departments";
import { cn } from "@/lib/utils";

/**
 * Departments as rows, each saying what is inside: an object, the department, its count
 * and its biggest categories in words. Never a grid of equal tiles of names —
 * three departments hold most of the catalogue, and "Seals & Bearings" alone does
 * not say O-rings.
 *
 * One column on phones, two from `md`. The hairlines between rows are the
 * list's own background showing through a 1px gap, so they stay single in
 * both layouts.
 */
export function DepartmentList({ departments, className }: { departments: DepartmentSummary[]; className?: string }) {
  return (
    <ul
      className={cn(
        "grid gap-px overflow-hidden rounded-card border border-line bg-line md:grid-cols-2",
        className,
      )}
    >
      {departments.map((department) => (
        <li
          key={department.domain}
          data-department={department.domain}
          className="bg-surface md:last:odd:col-span-2"
        >
          <DepartmentRow department={department} />
        </li>
      ))}
    </ul>
  );
}

function DepartmentRow({ department }: { department: DepartmentSummary }) {
  const image = objectImage(department.domain);
  return (
    <Link
      href={routes.department(department.domain)}
      className="flex min-h-11 items-center gap-3 px-3 py-2.5 text-ink hover:bg-ground"
    >
      {image ? (
        <PhotoFrame src={image} alt="" size={52} className="rounded-md" />
      ) : (
        <span className="grid size-[52px] shrink-0 place-items-center rounded-md border border-line bg-photo-frame">
          <DepartmentIcon domain={department.domain} className="size-6 text-ink-3" />
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline justify-between gap-2">
          <span className="text-base font-semibold">{department.label}</span>
          <span className="text-[13px] text-ink-3 tabular">{formatCount(department.count)}</span>
        </span>
        {department.inside.length > 0 && (
          // Wrapped, never cut: the phrase is the row's whole point.
          <span className="text-[13px] leading-snug text-pretty text-ink-2">
            {asPhrase(department.inside)}
          </span>
        )}
      </span>
    </Link>
  );
}
