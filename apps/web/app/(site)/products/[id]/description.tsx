import { cn } from "@/lib/utils";

/** Past this a description is clamped. Characters rather than measured lines,
 *  because the page is rendered on the server, which has no lines to measure. */
const CLAMP_FROM = 280;

/**
 * A shop's own description, clamped (four lines on a phone, six on a wide
 * screen) with "Read more" behind a `<details>`, so it opens without
 * JavaScript. The clamp is lifted by the open `<details>` beside the text,
 * via `:has()`, rather than by moving the text inside it: closed, a
 * `<details>` would hide the text entirely.
 *
 * Supplier prose, shown as written and never translated; `dir="auto"` for the
 * few that are in Arabic.
 */
export function Description({ heading, text }: { heading: string; text: string }) {
  const long = text.length > CLAMP_FROM || text.split("\n").length > 4;
  return (
    <section data-description className="group/description mt-6 lg:mt-5">
      <h2 className="text-[15px]">{heading}</h2>
      <p
        dir="auto"
        className={cn(
          "mt-1.5 text-sm leading-relaxed whitespace-pre-line text-ink-2",
          long &&
            "line-clamp-4 group-has-[details[open]]/description:line-clamp-none lg:line-clamp-6 lg:group-has-[details[open]]/description:line-clamp-none",
        )}
      >
        {text}
      </p>
      {long && (
        <details className="group">
          <summary className="inline-flex h-11 cursor-pointer list-none items-center text-sm font-medium text-link underline [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">Read more</span>
            <span className="hidden group-open:inline">Show less</span>
          </summary>
        </details>
      )}
    </section>
  );
}
