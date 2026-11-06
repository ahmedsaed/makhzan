/**
 * The brand, for the places CSS cannot reach: link-preview cards and app icons
 * are drawn by `next/og` from inline styles, not from globals.css, so they
 * need the palette as values.
 *
 * Every colour here is a copy of a token in app/globals.css, and
 * tests/brand.test.ts fails if one drifts from it. Components never import
 * these: they use the tokens (rule S1).
 */

export const SITE_NAME = "makhzan";

/** The headline, and the line every link preview leads with. */
export const TAGLINE = "Find parts and materials across Egypt's suppliers.";

/** The site's description where a page has nothing more specific to say. */
export const SITE_DESCRIPTION =
  "Find parts and materials across Egypt's suppliers: one search across Egyptian hardware and electronics shops. Every price shows when it was last checked; buying happens on the shop's own site.";

/** Light-theme tokens, by name (`--ground` is `palette.ground`). */
export const palette = {
  ground: "#f6f6f3",
  surface: "#ffffff",
  ink: "#15171c",
  ink2: "#4a4f5a",
  line: "#e3e3de",
  brand: "#c2410c",
  photoFrame: "#ffffff",
} as const;

/** Dark-theme tokens the brand needs: the logo's outline, and the ground
 *  a phone's browser bar matches. */
export const darkPalette = {
  ground: "#121316",
  ink: "#ececea",
} as const;

/**
 * The mark: a 2×2 parts organizer on a 48-unit grid. Three outlined
 * compartments and one filled, top right — many shops, one picked.
 */
export const MARK = {
  viewBox: 48,
  stroke: 3.5,
  outlined: [
    { x: 4, y: 4 },
    { x: 4, y: 26 },
    { x: 26, y: 26 },
  ],
  filled: { x: 26, y: 4 },
  size: 18,
  radius: 4,
} as const;

/** The mark as a standalone SVG document, in fixed colours. */
export function markSvg(ink: string = palette.ink, brand: string = palette.brand): string {
  const { size, radius, stroke } = MARK;
  const outlined = MARK.outlined
    .map(
      ({ x, y }) =>
        `<rect x="${x}" y="${y}" width="${size}" height="${size}" rx="${radius}" fill="none" stroke="${ink}" stroke-width="${stroke}"/>`,
    )
    .join("");
  const { x, y } = MARK.filled;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${MARK.viewBox} ${MARK.viewBox}">` +
    `${outlined}<rect x="${x}" y="${y}" width="${size}" height="${size}" rx="${radius}" fill="${brand}"/></svg>`
  );
}
