import type { ReactElement } from "react";

export type GlyphKind = "group" | "category";

export type Glyph = {
  /** The category's English name, for the contact sheet and the tests. */
  label: string;
  kind: GlyphKind;
  /** The strokes, drawn on the 24 × 24 grid; the `<svg>` around them sets the style. */
  body: ReactElement;
};
