import { ChevronLeft } from "lucide-react";

import { Breadcrumb, type Crumb } from "@/components/breadcrumb";
import { Link } from "@/components/link";
import { NotAnswering, Results } from "@/components/results";
import { SearchField } from "@/components/search-field";
import { Container } from "@/components/section";
import { departmentIcon } from "@/components/department-icon";
import { categoryNameOf, type Category } from "@/lib/api";
import { objectImage } from "@/lib/content/category-images";
import { formatCount } from "@/lib/format";
import { breadcrumbJsonLd } from "@/lib/metadata";
import { jsonLdText } from "@/lib/product";
import { routes } from "@/lib/routes";
import {
  fetchResults,
  parseResultsQuery,
  type RawParams,
  type ResultsQuery,
} from "@/lib/results-query";
import { asPhrase, totalOf, departmentLabel, departmentTree, type DepartmentNode } from "@/lib/departments";
import { cn } from "@/lib/utils";

import { balancedColumns, BrowseTile } from "./browse-tile";

export type { RawParams };

/**
 * A department, or one of its categories: the same page, narrowed. The header names
 * it and offers "Search in {department}"; the groups are object tiles, the selected
 * group's categories smaller ones; and the results start straight away, so no
 * page here is a dead-end list of links.
 *
 * The results are the search page's (components/results.tsx), on the same URL
 * contract (lib/results-query.ts), with the department — and on a category page the
 * category — fixed by the path. `?category=` may narrow further, but only to
 * something inside the page's own category; anything else is ignored rather
 * than allowed to show another department's products under this one's name.
 *
 * `categories` is null when the taxonomy could not be fetched: the page then
 * says so instead of failing.
 */
export async function DepartmentBrowse({
  department,
  categories,
  selected = null,
  params,
}: {
  department: string;
  /** The department's whole slice of the taxonomy, or null if it is unavailable. */
  categories: Category[] | null;
  /** The category the page is narrowed to; null on the department's own page. */
  selected?: Category | null;
  params: RawParams;
}) {
  const label = departmentLabel(department);
  if (!categories) {
    return (
      <>
        <DepartmentHeader department={department} heading={label} />
        <Container className="py-3.5">
          <NotAnswering title="The catalogue is not answering" />
        </Container>
      </>
    );
  }

  const tree = departmentTree(categories, selected?.ref ?? null);
  const pathname = selected ? routes.category(selected.ref) : routes.department(department);
  const query = scopedQuery(params, department, categories, selected);
  const data = await fetchResults(query, { baseCategory: selected?.ref });

  const heading = selected ? categoryNameOf(selected) : label;
  // The taxonomy's count, in and out of stock; the toolbar counts what shows.
  const count = selected
    ? totalOf(selected.ref, categories)
    : categories.reduce((sum, category) => sum + category.count, 0);
  const crumbs: Crumb[] = [
    { label: "Departments", href: routes.departments() },
    { label, href: routes.department(department) },
  ];
  if (tree.group && tree.group.ref !== selected?.ref) {
    crumbs.push({ label: categoryNameOf(tree.group), href: routes.category(tree.group.ref) });
  }
  if (selected) crumbs.push({ label: categoryNameOf(selected) });

  const shelf = tree.group ? tree.children : tree.top;
  const shelfTitle = tree.group
    ? `${categoryNameOf(tree.group)} · ${formatCount(tree.group.total)}`
    : `Biggest in ${label}`;
  // From `lg` a group tile says what is inside it, as a department does on /departments.
  const inside = (group: DepartmentNode) =>
    asPhrase(
      categories
        .filter((c) => c.parent === group.ref)
        .map((c) => ({ name: categoryNameOf(c), total: totalOf(c.ref, categories) }))
        .filter((c) => c.total > 0 && !/^other\b/i.test(c.name))
        .sort((a, b) => b.total - a.total)
        .slice(0, 3)
        .map((c) => c.name),
    ) || undefined;
  const tile = (node: DepartmentNode, size: "md" | "sm") => (
    <BrowseTile
      key={node.ref}
      href={routes.category(node.ref)}
      label={categoryNameOf(node)}
      image={objectImage(node.ref)}
      icon={departmentIcon(department)}
      count={node.total}
      hint={size === "md" ? inside(node) : undefined}
      current={node.ref === (size === "md" ? tree.group?.ref : selected?.ref)}
      size={size}
    />
  );
  const names = new Map(categories.map((c) => [c.ref, categoryNameOf(c)]));

  return (
    <>
      {/* Departments › department › group › category, for search results. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdText(breadcrumbJsonLd(crumbs)) }}
      />
      <DepartmentHeader
        department={department}
        heading={heading}
        count={count}
        crumbs={selected ? crumbs : undefined}
      >
        {tree.groups.length > 1 && (
          // On a phone as many columns as fit at 76px, so a long group name
          // ("Bearings & Transmission") wraps between words rather than inside
          // one. From `lg` the tiles lie on their side, in balanced rows.
          <nav
            aria-label="Groups"
            style={columns(tree.groups.length, 4, 5)}
            className={cn(
              "grid grid-cols-[repeat(auto-fill,minmax(4.75rem,1fr))] gap-1.5 sm:grid-cols-6",
              BALANCED,
            )}
          >
            {tree.groups.map((group) => tile(group, "md"))}
          </nav>
        )}
      </DepartmentHeader>

      <Container className="py-3.5">
        {shelf.length > 0 && (
          <section aria-labelledby="shelf-heading" className="mb-4 flex flex-col gap-2">
            <h2 id="shelf-heading" className="font-sans text-[13px] font-semibold text-ink-2">
              {shelfTitle}
            </h2>
            <nav
              aria-label="Categories"
              style={columns(shelf.length, 4, 6)}
              className={cn("grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8", BALANCED)}
            >
              {shelf.map((node) => tile(node, "sm"))}
            </nav>
          </section>
        )}

        {data.result ? (
          <Results
            pathname={pathname}
            raw={params}
            query={query}
            data={{ ...data, result: data.result }}
            names={names}
            locked={
              selected && query.category === selected.ref ? ["domain", "category"] : ["domain"]
            }
          />
        ) : (
          <NotAnswering />
        )}
      </Container>
    </>
  );
}

/** From `lg`, a tile grid takes its column count from `--cols-lg` / `--cols-xl`. */
const BALANCED =
  "lg:grid-cols-[repeat(var(--cols-lg),minmax(0,1fr))] lg:gap-2 xl:grid-cols-[repeat(var(--cols-xl),minmax(0,1fr))]";

function columns(count: number, lg: number, xl: number): React.CSSProperties {
  return {
    "--cols-lg": balancedColumns(count, lg),
    "--cols-xl": balancedColumns(count, xl),
  } as React.CSSProperties;
}

/**
 * The search page's query, with the department fixed and the category held inside
 * the page's own. A `?category=` from another department, or from outside this
 * category, is dropped; so are `domain` and `shop`, which the page decides.
 */
function scopedQuery(
  params: RawParams,
  department: string,
  categories: Category[],
  selected: Category | null,
): ResultsQuery {
  const query = parseResultsQuery(params);
  const parents = new Map(categories.map((c) => [c.ref, c.parent]));
  const within = (ref: string, ancestor: string) => {
    for (let at: string | null | undefined = ref; at; at = parents.get(at)) {
      if (at === ancestor) return true;
    }
    return false;
  };
  const asked = query.category;
  const category =
    asked && parents.has(asked) && (!selected || within(asked, selected.ref))
      ? asked
      : selected?.ref;
  return { ...query, domain: department, shop: undefined, category };
}

/** Back link or breadcrumb, the name, its count, and "Search in {department}". */
function DepartmentHeader({
  department,
  heading,
  count,
  crumbs,
  children,
}: {
  department: string;
  heading: string;
  count?: number;
  crumbs?: Crumb[];
  children?: React.ReactNode;
}) {
  const label = departmentLabel(department);
  return (
    <header className="border-b border-line bg-surface">
      <Container className="flex flex-col gap-2.5 pt-1 pb-3.5">
        {crumbs ? (
          <Breadcrumb items={crumbs} className="flex min-h-11 items-center" />
        ) : (
          <Link
            href={routes.departments()}
            className="inline-flex h-11 items-center gap-1 self-start text-sm text-ink-2 hover:text-ink"
          >
            <ChevronLeft aria-hidden="true" className="size-4" />
            All departments
          </Link>
        )}
        {/* From `lg` the search sits beside the name rather than under it. */}
        <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center lg:justify-between lg:gap-6">
          <div className="flex min-w-0 items-baseline justify-between gap-3 lg:justify-start">
            <h1 className="text-[26px] leading-tight">{heading}</h1>
            {count !== undefined && (
              <span data-catalogue-count className="shrink-0 text-[13px] text-ink-3 tabular">
                {formatCount(count)} products
              </span>
            )}
          </div>
          <SearchField
            compact
            label={`Search in ${label}`}
            placeholder={`Search in ${label}`}
            scope={{ domain: department }}
            className="md:max-w-xl lg:w-[26rem] lg:shrink-0"
          />
        </div>
        {children}
      </Container>
    </header>
  );
}
