/**
 * Full-size photos behind cached thumbnails.
 *
 * Some shops' pages serve only a resized, cached copy of each photo, 150px
 * tall: `…/uploads/cache/<date>/product/image/<stem>-q-80-h-150.webp`. The
 * original sits beside it without the cache segment and the resize suffix, as
 * `…/uploads/<date>/product/image/<stem>.jpeg` (sometimes `.png`); its
 * extension is not in the thumbnail's URL, so both are candidates, in the
 * order they are usually found.
 *
 * Only the product page asks for these. Lists and cards keep the thumbnails:
 * full-size photos for 24 results would be a lot of load on a shop's server
 * for a 72px box.
 */

// Groups: the URL up to `uploads/`, the folders after `cache/`, the file stem.
const CACHED_THUMBNAIL =
  /^([^?#]*\/uploads\/)cache\/((?:[^/?#]+\/)+)([^/?#]+?)-q-\d+(?:-[wh]-\d+)+\.webp(?:[?#].*)?$/i;

/** Extensions an original is found under, most common first. */
const ORIGINAL_EXTENSIONS = ["jpeg", "png"];

/**
 * The URLs the full-size original of `src` may be at, most likely first; empty
 * when `src` is not a cached thumbnail, which is every other shop's photo.
 */
export function fullSizeCandidates(src: string): string[] {
  const match = CACHED_THUMBNAIL.exec(src);
  if (!match) return [];
  const [, base, path, stem] = match;
  return ORIGINAL_EXTENSIONS.map((ext) => `${base}${path}${stem}.${ext}`);
}
