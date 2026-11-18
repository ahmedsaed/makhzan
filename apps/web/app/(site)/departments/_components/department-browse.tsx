import { ChevronLeft } from "lucide-react";

import { Breadcrumb, type Crumb } from "@/components/breadcrumb";
import { BrowseSheet } from "@/components/browse-sheet";
import { BrowseTree } from "@/components/browse-tree";
import { Link } from "@/components/link";
import { NotAnswering, Results } from "@/components/results";
import { SearchField } from "@/components/search-field";
import { Container } from "@/components/section";
import { categoryNameOf, type Category } from "@/lib/api";
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
import { totalOf, departmentLabel, departmentTree } from "@/lib/departments";

export type { RawParams };

/**
 * A department, one of its groups, or one of its categories: one template,
 * narrowed (layout B, the owner's choice of 18 November 2026).
 *
 * From `md` the department's tree is a sticky sidebar on the left
 * (components/browse-tree.tsx) and the main column holds the way back (or the
 * breadcrumb), the name with its count, "Search in {department}", and the
 * products straight away, so no page here is a dead-end list of links. On a
 * phone there is no category row at all: a floating "{place} · Browse" pill
 * opens the same tree as a bottom sheet (components/browse-sheet.tsx).
 *
 * The results are the search page's (components/results.tsx, its `browse`
 * toolbar: the three toggles and a Price chip, no rail, no category facet), on
 * the same URL contract (lib/results-query.ts), with the department, and on a
 * category page the category, fixed by the path. `?category=` may narrow
 * further, but only to something inside the page's own category; anything else
 * is ignored rather than allowed to show another department's products under
 * this one's name.
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
      <Container className="py-3.5">
        <PageHeading department={department} heading={label} />
        <NotAnswering title="The catalogue is not answering" className="mt-3" />
      </Container>
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
  const names = new Map(categories.map((c) => [c.ref, categoryNameOf(c)]));
  const treeProps = { department, categories, selected: selected?.ref ?? null };

  return (
    <>
      {/* Departments › department › group › category, for search results. */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdText(breadcrumbJsonLd(crumbs)) }}
      />
      <Container className="pt-1 pb-3.5 md:grid md:grid-cols-[15rem_minmax(0,1fr)] md:gap-x-6 md:pt-4 lg:grid-cols-[17.5rem_minmax(0,1fr)] lg:gap-x-8">
        {/* The sidebar. Hidden on a phone, where the sheet shows the same tree;
            but shown there as its target, which is where the pill leads with
            JavaScript off. */}
        <aside id="browse-tree" className="hidden target:block md:block">
          <div className="md:sticky md:top-4 md:max-h-[calc(100svh-2rem)] md:overflow-y-auto md:overscroll-contain md:pb-4">
            <p className="px-2.5 pt-2 pb-2 text-xs font-semibold tracking-[0.06em] text-ink-2 uppercase">
              Browse {label}
            </p>
            <div className="rounded-card border border-line bg-surface p-1.5">
              <BrowseTree {...treeProps} density="sidebar" />
            </div>
          </div>
        </aside>

        {/* Bottom padding on a phone, so the floating pill never covers the last card. */}
        <div data-browse-main className="min-w-0 pb-24 md:pb-0">
          <PageHeading
            department={department}
            heading={heading}
            count={count}
            crumbs={selected ? crumbs : undefined}
          />
          {data.result ? (
            <Results
              variant="browse"
              pathname={pathname}
              raw={params}
              query={query}
              data={{ ...data, result: data.result }}
              names={names}
              locked={
                selected && query.category === selected.ref ? ["domain", "category"] : ["domain"]
              }
              className="mt-3"
            />
          ) : (
            <NotAnswering className="mt-3" />
          )}
        </div>
      </Container>

      <BrowseSheet place={heading} title={`Browse ${label}`}>
        <BrowseTree {...treeProps} density="sheet" />
      </BrowseSheet>
    </>
  );
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
function PageHeading({
  department,
  heading,
  count,
  crumbs,
}: {
  department: string;
  heading: string;
  count?: number;
  crumbs?: Crumb[];
}) {
  const label = departmentLabel(department);
  return (
    <header className="flex flex-col gap-2.5">
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
          className="md:max-w-xl lg:w-[22rem] lg:shrink-0"
        />
      </div>
    </header>
  );
}
