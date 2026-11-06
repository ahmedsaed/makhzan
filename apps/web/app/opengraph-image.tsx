import { fetchStats } from "@/lib/api";
import { TAGLINE } from "@/lib/brand";
import { totalsLine } from "@/lib/metadata";
import { OG_SIZE, renderCard } from "@/lib/og";

/**
 * The site's own link preview, and the default for every page without one of
 * its own (search, the static pages). The tagline and the live totals; with
 * the API down, the tagline alone.
 */

export const alt = "makhzan: find parts and materials across Egypt's suppliers";
export const size = OG_SIZE;
export const contentType = "image/png";
/** An hour: the totals move with the weekly sweep, not by the minute. */
export const revalidate = 3600;

export default async function Image() {
  const stats = await fetchStats().catch(() => null);
  return renderCard({ title: TAGLINE, lines: [stats ? totalsLine(stats) : null] });
}
