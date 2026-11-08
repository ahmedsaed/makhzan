import { OG_SIZE } from "@/lib/og";

import DepartmentImage from "../opengraph-image";

/**
 * A category's link preview is its department's card. Its own file all the same:
 * a page that sets its own `openGraph` does not inherit a parent segment's
 * image, it falls back to the site's (lib/metadata.ts).
 */

export const alt = "A department on makhzan: how many products it holds, and its biggest categories";
export const size = OG_SIZE;
export const contentType = "image/png";
export const revalidate = 3600;

export default function Image({ params }: { params: Promise<{ department: string }> }) {
  return DepartmentImage({ params });
}
