import { cn } from "@/lib/utils";

/** Lines shown before "Read more". */
export const CLAMP_LINES = 25;

/**
 * Characters per line, roughly, in the description's column: a 375px phone
 * fits about 45 of them, the desktop wide column about 100. Rounded up, so an
 * estimate errs towards "fits": a text judged short is never clamped, so
 * nothing can be hidden without a button to show it.
 */
const PHONE_CHARS_PER_LINE = 48;
const WIDE_CHARS_PER_LINE = 105;

/** How many lines `text` takes wrapped at `perLine` characters, paragraph by paragraph. */
export function estimateLines(text: string, perLine: number): number {
  return text
    .split("\n")
    .reduce((lines, paragraph) => lines + Math.max(1, Math.ceil(paragraph.length / perLine)), 0);
}

/**
 * A shop's own description, clamped to 25 lines with a fade and "Read more".
 *
 * Decided on the server, so the page is drawn once in its final shape: no
 * measuring, nothing that moves after load, no flash of the full text. The
 * estimate is made for the phone and the wide column separately, so a text
 * long only on a phone gets its clamp and button there alone.
 *
 * "Read more" is a `<details>`, so it opens without JavaScript. The clamp is
 * lifted by the open `<details>` beside the text, via `:has()`, rather than by
 * moving the text inside it: closed, a `<details>` would hide it entirely.
 *
 * Supplier prose, shown as written and never translated; `dir="auto"` for the
 * few that are in Arabic.
 */
export function Description({ text }: { text: string }) {
  const long = estimateLines(text, PHONE_CHARS_PER_LINE) > CLAMP_LINES;
  const longWide = estimateLines(text, WIDE_CHARS_PER_LINE) > CLAMP_LINES;
  // Tailwind reads class names from the source, so each is spelled out whole.
  // The standard `line-clamp` beside Tailwind's `-webkit-line-clamp`.
  return (
    <section data-description className="group/description mt-6 lg:mt-5">
      <h3 className="text-[15px]">Description</h3>
      <div className="relative mt-1.5">
        <p
          dir="auto"
          className={cn(
            "text-sm leading-relaxed whitespace-pre-line text-ink-2",
            long &&
              "line-clamp-25 [line-clamp:25] group-has-[details[open]]/description:line-clamp-none group-has-[details[open]]/description:[line-clamp:none]",
            long &&
              (longWide
                ? "lg:line-clamp-25 lg:[line-clamp:25] lg:group-has-[details[open]]/description:line-clamp-none lg:group-has-[details[open]]/description:[line-clamp:none]"
                : "lg:line-clamp-none lg:[line-clamp:none]"),
          )}
        >
          {text}
        </p>
        {long && (
          <div
            aria-hidden="true"
            data-description-fade
            className={cn(
              "pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-linear-to-t from-ground group-has-[details[open]]/description:hidden",
              !longWide && "lg:hidden",
            )}
          />
        )}
      </div>
      {long && (
        <details className={cn("group", !longWide && "lg:hidden")}>
          <summary className="inline-flex h-11 cursor-pointer list-none items-center text-sm font-medium text-link underline [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">Read more</span>
            <span className="hidden group-open:inline">Show less</span>
          </summary>
        </details>
      )}
    </section>
  );
}
