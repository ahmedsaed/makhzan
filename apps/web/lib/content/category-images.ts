/**
 * One iconic object photo per department and category, McMaster-Carr style: a photo
 * of a thing is recognised faster than its name is read.
 *
 * Keyed by department (`tools`) or category ref (`tools:precision-measure`), never a
 * bare category slug, which names a category in several departments at once.
 *
 * Empty until the photos are curated (about 60: the 16 departments and their
 * groups). That is a content task, not a code one: each should be a clean
 * product shot on white, licensed for reuse. Until then ObjectTile draws a
 * neutral line icon instead.
 */
const IMAGES: Record<string, string> = {};

export function objectImage(key: string): string | null {
  return IMAGES[key] ?? null;
}
