import { cn } from "@/lib/utils";

/**
 * Past these a description is clamped: three lines on a phone (about 45
 * characters each), four on a wide screen (about 100). Characters rather than
 * measured lines, because the page is rendered on the server, which has no
 * lines to measure.
 */
const PHONE_CLAMP_FROM = 140;
const WIDE_CLAMP_FROM = 380;

/**
 * A shop's own description, clamped tight (three lines on a phone, four on a
 * wide screen) with "Read more" behind a `<details>`, so it opens without
 * JavaScript. Tight because it is the shop's text, not makhzan's: the facts
 * and similar products above it are what no shop's page has. The clamp is
 * lifted by the open `<details>` beside the text, via `:has()`, rather than by
 * moving the text inside it: closed, a `<details>` would hide the text
 * entirely. A text that fits four wide lines is clamped on a phone only, and
 * its "Read more" shows only there.
 *
 * Supplier prose, shown as written and never translated; `dir="auto"` for the
 * few that are in Arabic.
 */
export function Description({ heading, text }: { heading: string; text: string }) {
  const lines = text.split("\n").length;
  const long = text.length > PHONE_CLAMP_FROM || lines > 3;
  const longWide = text.length > WIDE_CLAMP_FROM || lines > 4;
  return (
    <section data-description className="group/description mt-6 lg:mt-5">
      <h2 className="text-[15px]">{heading}</h2>
      <p
        dir="auto"
        className={cn(
          "mt-1.5 text-sm leading-relaxed whitespace-pre-line text-ink-2",
          long && "line-clamp-3 group-has-[details[open]]/description:line-clamp-none",
          long &&
            (longWide
              ? "lg:line-clamp-4 lg:group-has-[details[open]]/description:line-clamp-none"
              : "lg:line-clamp-none"),
        )}
      >
        {text}
      </p>
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
