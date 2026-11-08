import { ChevronRight } from "lucide-react";

import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { DepartmentIcon } from "@/components/department-icon";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import type { DirectoryGroup, DirectoryLink, DirectoryDepartment } from "@/lib/department-directory";
import { asPhrase } from "@/lib/departments";
import { cn } from "@/lib/utils";

import { DepartmentDisclosure } from "./department-disclosure";

/**
 * Every department as a directory entry: its name and size, and its categories as
 * links with their counts.
 *
 * On a phone it is the list the home page shows — a row per department saying what
 * is inside — with each department's links folded under a chevron. From `md` each
 * department is a card and its links are always out. The major departments span the
 * full width and map every group with its categories in columns; the rest
 * share a grid, listing more categories the bigger they are, and the next
 * tier down (`wide`) takes two cells on wide screens with its links in two
 * columns. Size is the fact the layout shows: three departments hold most of the
 * catalogue.
 *
 * The hairlines between phone rows are the list's background showing through
 * a 1px gap, as in DepartmentList; from `md` the gap opens and each card draws its
 * own border.
 */
export function DepartmentDirectory({ departments }: { departments: DirectoryDepartment[] }) {
  return (
    <ul
      className={cn(
        "grid grid-cols-1 gap-px overflow-hidden rounded-card border border-line bg-line",
        "md:grid-cols-2 md:gap-3 md:overflow-visible md:rounded-none md:border-0 md:bg-transparent",
        "lg:grid-cols-3 xl:grid-cols-4",
      )}
    >
      {departments.map((department) => (
        <li
          key={department.domain}
          data-department={department.domain}
          data-major={department.major ? "true" : undefined}
          className={cn(
            "min-w-0 bg-surface md:rounded-card md:border md:border-line",
            department.major && "md:col-span-full",
            department.wide && "xl:col-span-2",
          )}
        >
          <DepartmentDisclosure label={department.label} head={<DepartmentHead department={department} />}>
            {department.major ? <GroupColumns department={department} /> : <CategoryList department={department} />}
          </DepartmentDisclosure>
        </li>
      ))}
    </ul>
  );
}

function DepartmentHead({ department }: { department: DirectoryDepartment }) {
  const image = objectImage(department.domain);
  const frame = department.major ? "size-[52px] md:size-14" : "size-[52px] md:size-11";
  return (
    <Link
      href={routes.department(department.domain)}
      className={cn(
        "group flex min-h-11 items-center gap-3 py-2.5 pl-3 text-ink hover:bg-ground",
        "md:rounded-t-card md:px-4 md:py-3 md:hover:bg-transparent",
      )}
    >
      {image ? (
        <PhotoFrame src={image} alt="" size={52} className={cn("rounded-md", frame)} />
      ) : (
        <span
          className={cn(
            "grid shrink-0 place-items-center rounded-md border border-line bg-photo-frame",
            frame,
          )}
        >
          <DepartmentIcon domain={department.domain} className="size-6 text-ink-3" />
        </span>
      )}
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline justify-between gap-2 md:justify-start md:gap-3">
          <h2
            className={cn(
              "font-sans text-base font-semibold md:font-display md:font-bold md:group-hover:text-link",
              department.major && "md:text-xl",
            )}
          >
            {department.label}
          </h2>
          <span className="text-[13px] text-ink-3 tabular">
            {formatCount(department.count)}
            <span className="hidden md:inline"> products</span>
          </span>
        </span>
        {department.inside.length > 0 && (
          <span className="text-[13px] leading-snug text-pretty text-ink-2 md:hidden">
            {asPhrase(department.inside)}
          </span>
        )}
        <span className="hidden text-[13px] text-ink-3 tabular md:block">
          {department.categoryCount} {department.categoryCount === 1 ? "category" : "categories"}
          {department.major && (
            <>
              {" "}
              in {department.groups.length} groups · {Math.round(department.share * 100)}% of all products
            </>
          )}
        </span>
      </span>
    </Link>
  );
}

/** A major department: every group, each with its categories, in columns. */
function GroupColumns({ department }: { department: DirectoryDepartment }) {
  return (
    <div className="border-t border-line px-3 pt-3 pb-1 md:px-4 md:pt-4">
      <div className="gap-8 sm:columns-2 lg:columns-3 xl:columns-4">
        {department.groups.map((group) => (
          <Group key={group.ref} group={group} />
        ))}
      </div>
    </div>
  );
}

function Group({ group }: { group: DirectoryGroup }) {
  return (
    <section data-group={group.ref} className="mb-4 break-inside-avoid">
      <h3 className="font-sans">
        <EntryLink link={group} className="font-semibold text-ink" />
      </h3>
      {group.categories.length > 0 && (
        <ul>
          {group.categories.map((category) => (
            <li key={category.ref}>
              <EntryLink link={category} />
            </li>
          ))}
        </ul>
      )}
      {group.more > 0 && (
        <MoreLink href={group.href}>
          {group.more} more in {group.name}
        </MoreLink>
      )}
    </section>
  );
}

/** A minor department: its biggest categories, then the way to the rest. */
function CategoryList({ department }: { department: DirectoryDepartment }) {
  return (
    <div className="border-t border-line px-3 pt-2 pb-2 md:px-4 md:pb-3">
      <ul className={cn(department.wide && "gap-8 xl:columns-2")}>
        {department.categories.map((category) => (
          <li key={category.ref}>
            <EntryLink link={category} />
          </li>
        ))}
      </ul>
      {department.more > 0 && (
        <MoreLink href={routes.department(department.domain)}>
          All {department.categoryCount} categories in {department.label}
        </MoreLink>
      )}
    </div>
  );
}

/** A name and its count, set like an index: name left, count right. */
function EntryLink({ link, className }: { link: DirectoryLink; className?: string }) {
  return (
    <Link
      href={link.href}
      className={cn(
        "flex min-h-11 items-center justify-between gap-3 text-sm text-ink-2 hover:text-link",
        "md:min-h-0 md:py-1",
        className,
      )}
    >
      <span className="min-w-0">{link.name}</span>{" "}
      <span className="shrink-0 text-[13px] font-normal text-ink-3 tabular">
        {formatCount(link.count)}
      </span>
    </Link>
  );
}

function MoreLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="flex min-h-11 items-center gap-0.5 text-sm text-link hover:underline md:min-h-0 md:py-1"
    >
      {children}
      <ChevronRight aria-hidden="true" className="size-4" />
    </Link>
  );
}
