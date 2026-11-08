import { categoryNameOf, type Category } from "@/lib/api";
import { routes } from "@/lib/routes";
import { leavesOf, totalOf, departmentSummaries, type DepartmentSummary } from "@/lib/departments";

/**
 * The all-departments page as a directory: every department with its categories as
 * links, drawn by how much each department holds.
 *
 * Three departments hold most of the catalogue, so they are not drawn like the
 * rest. A department with at least `MAJOR_SHARE` of all products is "major": it
 * lists every group with that group's categories, because that is where a
 * buyer needs a map. The others list their biggest categories, more of them
 * the bigger the department, and link to the rest; the biggest of those are `wide`.
 */

export const MAJOR_SHARE = 0.1;

/** A minor department this big is `wide`: two cells of the grid, more links. */
export const WIDE_COUNT = 1000;

export type DirectoryLink = { ref: string; name: string; count: number; href: string };

export type DirectoryGroup = DirectoryLink & {
  categories: DirectoryLink[];
  /** Categories in the group that are not listed. */
  more: number;
};

export type DirectoryDepartment = DepartmentSummary & {
  major: boolean;
  /** A minor department big enough to take two cells of the grid. */
  wide: boolean;
  /** Its share of the whole catalogue, 0–1. */
  share: number;
  /** Categories with products: the leaves of its tree. */
  categoryCount: number;
  /** Major departments: every group with products, largest first. */
  groups: DirectoryGroup[];
  /** Minor departments: the biggest categories. */
  categories: DirectoryLink[];
  /** Categories with products that `categories` leaves out. */
  more: number;
};

/** How many categories a group lists before "N more". */
const PER_GROUP = 6;

/** How many categories a minor department lists: more for a bigger department. */
export function categoryLimit(count: number): number {
  if (count >= WIDE_COUNT) return 10;
  if (count >= 200) return 6;
  return 4;
}

const isOther = (category: Category) => /^other\b/i.test(category.name_en);

/** Largest first, but an "Other …" bucket always last: it is the least
 *  telling name however big it is. */
function ranked(categories: Category[], all: Category[]): DirectoryLink[] {
  return categories
    .map((category) => ({ category, count: totalOf(category.ref, all) }))
    .filter(({ count }) => count > 0)
    .sort((a, b) => Number(isOther(a.category)) - Number(isOther(b.category)) || b.count - a.count)
    .map(({ category, count }) => ({
      ref: category.ref,
      name: categoryNameOf(category),
      count,
      href: routes.category(category.ref),
    }));
}

export function departmentDirectory(categories: Category[]): DirectoryDepartment[] {
  const summaries = departmentSummaries(categories);
  const total = summaries.reduce((sum, department) => sum + department.count, 0);

  return summaries.map((department) => {
    const own = categories.filter((category) => category.domain === department.domain);
    const leaves = ranked(leavesOf(own), own);
    const share = total > 0 ? department.count / total : 0;
    const major = share >= MAJOR_SHARE;

    const groups: DirectoryGroup[] = major
      ? ranked(
          own.filter((category) => !category.parent),
          own,
        ).map((group) => {
          const children = ranked(
            own.filter((category) => category.parent === group.ref),
            own,
          );
          return {
            ...group,
            categories: children.slice(0, PER_GROUP),
            more: Math.max(0, children.length - PER_GROUP),
          };
        })
      : [];
    const listed = major ? [] : leaves.slice(0, categoryLimit(department.count));

    return {
      ...department,
      major,
      wide: !major && department.count >= WIDE_COUNT,
      share,
      categoryCount: leaves.length,
      groups,
      categories: listed,
      more: major ? 0 : leaves.length - listed.length,
    };
  });
}
