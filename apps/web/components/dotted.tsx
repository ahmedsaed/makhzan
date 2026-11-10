import { Children, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Phrases on one line, " · " between them, wrapping whole: "12 Example Street
 * · Open in maps". A phrase that wraps to a new line never drags a dot with
 * it: each phrase carries its dot in front, and the dot of whichever phrase
 * starts a line falls in a strip clipped off the left edge. A dot left at the
 * end of a line, or opening the next, read as a stray mark.
 */
export function Dotted({
  children,
  className,
  ...props
}: {
  children: ReactNode;
  className?: string;
} & Record<`data-${string}`, string | boolean | undefined>) {
  const items = Children.toArray(children).filter(Boolean);
  return (
    <div {...props} className={cn("overflow-x-clip", className)}>
      <div className="-ms-3 flex flex-wrap items-baseline">
        {items.map((item, index) => (
          <span key={index} className="min-w-0 ps-3 has-[details[open]]:basis-full">
            {/* Real text, so the line still reads "a · b" when copied or read
                aloud; drawn in the phrase's own padding, on its first line.
                Not positioned: a positioned phrase would paint over the 44px
                tap extension of a link on the line above (INLINE_LINK). */}
            {index > 0 && (
              <span className="-ms-3 inline-block w-3 text-center whitespace-pre text-ink-3">
                {" · "}
              </span>
            )}
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * For a link that reads as words in a line of text yet takes a 44px tap on a
 * phone (S4): an invisible box, 44px tall, centred on it, so lines stay close
 * rather than each growing to 44px.
 */
export const TAP_EXTENSION =
  "relative after:absolute after:inset-x-0 after:top-1/2 after:h-11 after:-translate-y-1/2 after:content-[''] lg:after:hidden";

/** The same, as an orange link: "Open in maps", "Tell us". */
export const INLINE_LINK = `${TAP_EXTENSION} font-semibold text-link hover:underline`;
