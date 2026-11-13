/**
 * Inline copy with links in it, for the site's own pages (/about, /faq,
 * /contact, /terms), kept as data apart from its markup like privacy.ts.
 *
 * A paragraph is a list of parts: plain text, a link to one of our pages, an
 * email address (a `mailto:` link), a word in bold, an address shown as text, or the "Report a problem"
 * button drawn as an inline illustration (not a working button: the real one
 * is beside each product's title). components/prose.tsx renders it;
 * `plainText` flattens it for structured data and tests.
 */
export type Inline =
  | string
  | { link: string; href: string }
  | { email: string }
  | { strong: string }
  /** An address shown as text, in the monospace face, beside a button that sends to it. */
  | { mono: string }
  | { flag: string };

export type Rich = Inline[];

export function plainText(parts: Rich): string {
  return parts
    .map((part) => {
      if (typeof part === "string") return part;
      if ("link" in part) return part.link;
      if ("email" in part) return part.email;
      if ("strong" in part) return part.strong;
      if ("mono" in part) return part.mono;
      return part.flag;
    })
    .join("");
}

/** Every address a block of copy links to, `mailto:` included. */
export function hrefsOf(parts: Rich): string[] {
  return parts.flatMap((part) => {
    if (typeof part === "string") return [];
    if ("link" in part) return [part.href];
    if ("email" in part) return [`mailto:${part.email}`];
    return [];
  });
}
