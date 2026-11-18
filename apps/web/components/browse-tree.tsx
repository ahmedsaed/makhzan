import { CategoryIcon, hasCategoryIcons, tileIcon } from "@/components/category-icons";
import { Funnel, TreeGroup } from "@/components/browse-tree-group";
import { Link } from "@/components/link";
import { categoryNameOf, type Category } from "@/lib/api";
import { departmentLabel, departmentTree, totalOf, type DepartmentNode } from "@/lib/departments";
import { formatCount } from "@/lib/format";
import { routes } from "@/lib/routes";
import { cn } from "@/lib/utils";

/**
 * A department's tree, the navigation of every department, group and category
 * page (layout B, the owner's choice of 18 November 2026): "All of
 * {department}", then its groups by size, each with its object icon and count,
 * expandable to its categories with their symbols and counts.
 *
 * The same tree is the desktop sidebar and the phone's bottom sheet
 * (`density`). The place you are is outlined and bold, never filled
 * (`aria-current="page"`); its group starts expanded, the others collapsed but
 * expandable in place. A group holding one category links straight to that
 * category, since its own page would show the same products. A department
 * whose icons are not drawn yet shows its categories plain, and its groups
 * keep the department's line icon.
 */
export function BrowseTree({
  department,
  categories,
  selected,
  density,
}: {
  department: string;
  categories: Category[];
  /** The ref the page is narrowed to; null on the department's own page. */
  selected: string | null;
  /** `sidebar`: 36px rows for a pointer; `sheet`: 44px rows for a finger (S4). */
  density: "sidebar" | "sheet";
}) {
  const { groups, group: currentGroup } = departmentTree(categories, selected);
  const drawn = hasCategoryIcons(department);
  const total = categories.reduce((sum, category) => sum + category.count, 0);
  const label = departmentLabel(department);
  const sheet = density === "sheet";
  // In the phone sheet every row is a tinted button, 44px, 8px corners (the
  // owner's sheet-motion mockup, option A, and his "same button style" for the
  // categories); in the sidebar, plain rows. Counts on the tint are ink-2:
  // ink-3 falls short of 4.5:1 on the light tint (S2).
  const row = cn(
    "flex w-full items-center gap-2.5 px-2.5 text-ink",
    sheet
      ? "min-h-11 rounded-md bg-tint text-[15px] transition-colors duration-150 hover:bg-line"
      : "min-h-9 rounded-md py-1 text-sm hover:bg-ground",
  );
  // The place you are: a 2px outline, never a fill, on whichever button it is.
  // Its outline would hide the keyboard's focus ring (the same property), so
  // under focus it becomes the site's ring instead: the link colour, 2px out.
  const current =
    "font-semibold outline-2 -outline-offset-2 outline-chip-on focus-visible:outline-link focus-visible:outline-offset-2";
  const count = cn(
    "ms-auto shrink-0 ps-2 text-[13px] font-normal tabular",
    sheet ? "text-ink-2" : "text-ink-3",
  );

  const childrenOf = (node: DepartmentNode) =>
    categories
      .filter((c) => c.parent === node.ref)
      .map((c) => ({ ...c, total: totalOf(c.ref, categories) }))
      .filter((c) => c.total > 0)
      .sort((a, b) => b.total - a.total);

  return (
    <nav aria-label={`Browse ${label}`} data-browse-tree={density}>
      <ul role="list" className="flex flex-col gap-0.5">
        <li>
          <Link
            href={routes.department(department)}
            aria-current={selected === null ? "page" : undefined}
            className={cn(row, selected === null && current)}
          >
            <span className="min-w-0 flex-1">All of {label}</span>
            <span className={count}>{formatCount(total)}</span>
          </Link>
        </li>
        {groups.map((node) => {
          const kids = childrenOf(node);
          const Icon = tileIcon(node.ref, department);
          const icon = <Icon strokeWidth={1.5} className="size-[18px] shrink-0 text-ink-2" />;
          // A group of one category goes straight to it; the group's own page
          // would list exactly the same products. Only when the counts agree:
          // products filed on the group itself would make it more than its child.
          const only = kids.length === 1 && kids[0].total === node.total ? kids[0] : null;
          if (kids.length === 0 || only) {
            const target = only ?? node;
            const here = selected === node.ref || (only !== null && selected === only.ref);
            const link = (
              <Link
                href={routes.category(target.ref)}
                aria-current={here ? "page" : undefined}
                data-tree-group={node.ref}
                className={cn(row, here && current)}
              >
                {icon}
                <span className="min-w-0 flex-1">{categoryNameOf(node)}</span>
                <span className={count}>{formatCount(node.total)}</span>
              </Link>
            );
            if (!sheet) return <li key={node.ref}>{link}</li>;
            // In the sheet the row keeps every group's two-button shape, so the
            // names line up (the owner, 18 November 2026): the funnel is there
            // but disabled, dimmed, out of the tab order, and says why.
            return (
              <li key={node.ref}>
                <div className="flex items-center gap-1.5">
                  <div className="min-w-0 flex-1">{link}</div>
                  <button
                    type="button"
                    disabled
                    data-funnel="none"
                    aria-label={`No subcategories in ${categoryNameOf(node)}`}
                    className="grid size-11 shrink-0 cursor-default place-items-center rounded-md bg-tint/50 text-ink-3"
                  >
                    <Funnel />
                  </button>
                </div>
              </li>
            );
          }
          const isCurrent = selected === node.ref;
          return (
            <TreeGroup
              key={node.ref}
              groupRef={node.ref}
              name={categoryNameOf(node)}
              defaultOpen={currentGroup?.ref === node.ref}
              density={density}
              head={
                <Link
                  href={routes.category(node.ref)}
                  aria-current={isCurrent ? "page" : undefined}
                  data-tree-group={node.ref}
                  className={cn(row, !sheet && "pe-1", isCurrent && current)}
                >
                  {icon}
                  <span className="min-w-0 flex-1">{categoryNameOf(node)}</span>
                  <span className={count}>{formatCount(node.total)}</span>
                </Link>
              }
            >
              {kids.map((kid) => {
                const here = selected === kid.ref;
                return (
                  <li key={kid.ref}>
                    <Link
                      href={routes.category(kid.ref)}
                      aria-current={here ? "page" : undefined}
                      data-tree-category={kid.ref}
                      className={cn(row, here && current)}
                    >
                      {drawn && (
                        <CategoryIcon iconRef={kid.ref} className="size-4 shrink-0 text-ink-2" />
                      )}
                      <span className="min-w-0 flex-1 leading-snug">{categoryNameOf(kid)}</span>
                      <span className={count}>{formatCount(kid.total)}</span>
                    </Link>
                  </li>
                );
              })}
            </TreeGroup>
          );
        })}
      </ul>
    </nav>
  );
}
