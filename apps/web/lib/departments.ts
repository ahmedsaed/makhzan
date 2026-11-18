import type { Category } from "@/lib/api";

/**
 * Departments are what the backend calls domains. The API has no /domains endpoint —
 * a department exists because categories belong to it — so names are derived from
 * the slug and sizes from the categories' counts.
 */

export type Department = { domain: string; label: string; count: number };

/** "seals-bearings" → "Seals & Bearings". */
export function departmentLabel(domain: string): string {
  return domain
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" & ");
}

/** Roll the flat category payload up into departments, largest first. */
export function departmentsFrom(categories: Category[]): Department[] {
  const totals = new Map<string, number>();
  for (const category of categories) {
    totals.set(category.domain, (totals.get(category.domain) ?? 0) + category.count);
  }
  return [...totals.entries()]
    .map(([domain, count]) => ({ domain, label: departmentLabel(domain), count }))
    .sort((a, b) => b.count - a.count);
}

// --------------------------------------------------------------------------- //
// What is inside a department, and how its tree is browsed
// --------------------------------------------------------------------------- //

/** A department as the home and all-departments pages list it: its name, its size, and
 *  what is inside it, in words. */
export type DepartmentSummary = Department & { inside: string[] };

/** Leaves hold the products; parents are browse groups. */
export function leavesOf(categories: Category[]): Category[] {
  const parents = new Set(categories.map((category) => category.parent));
  return categories.filter((category) => !parents.has(category.ref));
}

/**
 * Counts are per category, not per subtree: a group's own count is what is
 * filed on it directly, usually nothing. This is the subtree's total.
 */
export function totalOf(ref: string, categories: Category[]): number {
  const own = categories.find((category) => category.ref === ref)?.count ?? 0;
  return categories
    .filter((category) => category.parent === ref)
    .reduce((sum, child) => sum + totalOf(child.ref, categories), own);
}

/**
 * "Resistors, batteries & chargers, connectors, ICs": the names read as one
 * phrase, so only its first word keeps its capital. The rest of the first name
 * is lowered like any other, or the list reads in two styles ("Batteries &
 * Chargers, power supplies"). A word is lowered only when it is plainly an
 * ordinary capitalised word; "PLCs", "3D", "O-Rings" and "PTFE" keep theirs.
 */
export function asPhrase(names: string[]): string {
  return names
    .map((name, index) =>
      name
        .split(" ")
        .map((word, at) =>
          (index > 0 || at > 0) && /^[A-Z][a-z]+$/.test(word) ? word.toLowerCase() : word,
        )
        .join(" "),
    )
    .join(", ");
}

/**
 * A department's biggest categories, which say what is inside far better than its
 * name does ("Seals & Bearings": O-rings, bearings, oil seals). "Other …"
 * buckets are skipped: they are the one thing a name cannot describe.
 */
export function insideOf(domain: string, categories: Category[], limit = 4): string[] {
  return leavesOf(categories.filter((category) => category.domain === domain))
    .filter((category) => category.count > 0 && !/^other\b/i.test(category.name_en))
    .sort((a, b) => b.count - a.count)
    .slice(0, limit)
    .map((category) => category.name_en);
}

/** Every department that has products, with what is inside, largest first. */
export function departmentSummaries(categories: Category[], limit = 4): DepartmentSummary[] {
  return departmentsFrom(categories)
    .filter((department) => department.count > 0)
    .map((department) => ({
      ...department,
      inside: insideOf(department.domain, categories, limit),
    }));
}

export type DepartmentNode = Category & { total: number };

/**
 * One department's tree as its page shows it: the top-level groups, the selected
 * group and its categories, and — when nothing is selected — the department's
 * biggest categories. Empty branches are left out: a tile that leads to
 * nothing is a dead end.
 *
 * `selected` is the category the page is narrowed to; its group is the
 * top-level category above it, or itself when it is top level.
 */
export function departmentTree(categories: Category[], selected: string | null = null) {
  const withTotals = (list: Category[]): DepartmentNode[] =>
    list
      .map((category) => ({
        ...category,
        total: totalOf(category.ref, categories),
      }))
      .filter((node) => node.total > 0)
      .sort((a, b) => b.total - a.total);

  const byRef = new Map(categories.map((category) => [category.ref, category]));
  let root = selected ? byRef.get(selected) : undefined;
  while (root?.parent && byRef.has(root.parent)) root = byRef.get(root.parent);

  const groups = withTotals(categories.filter((category) => !category.parent));
  const group = root ? (groups.find((node) => node.ref === root.ref) ?? null) : null;
  const children = group ? withTotals(categories.filter((c) => c.parent === group.ref)) : [];
  // A flat department has nothing to add here: its groups already are its categories.
  const nested = groups.some((node) => categories.some((c) => c.parent === node.ref));
  // A shortcut that leads where a group tile already does is the same thing
  // shown twice ("Accessories & Other" 1,202 and its only category "Accessories"
  // 1,202): a top-level leaf, or a group's only non-empty category, is left out.
  // The eight biggest are taken first, so leaving one out shortens the shelf
  // rather than pulling in a smaller category (the approved mockup).
  const live = new Map<string | null, number>();
  for (const node of withTotals(categories)) {
    live.set(node.parent, (live.get(node.parent) ?? 0) + 1);
  }
  // The page shows group tiles only when there are two or more.
  const tiles = new Set(groups.length > 1 ? groups.map((g) => g.ref) : []);
  const repeatsGroup = (node: DepartmentNode) =>
    !node.parent || (tiles.has(node.parent) && live.get(node.parent) === 1);
  const top =
    !group && nested
      ? withTotals(leavesOf(categories))
          .slice(0, 8)
          .filter((node) => !repeatsGroup(node))
      : [];

  return { groups, group, children, top };
}
