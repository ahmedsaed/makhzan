import { Fragment } from "react";

import { Link } from "@/components/link";
import { cn } from "@/lib/utils";

export type Crumb = { label: string; href?: string };

/**
 * Trade › group › category. The last crumb is the current page and is not a
 * link; any crumb without an href is plain text too.
 *
 * `trail` is for a page that sits *under* the last crumb rather than being it
 * (a product under its category): every crumb with an href links.
 */
export function Breadcrumb({
  items,
  className,
  trail = false,
}: {
  items: Crumb[];
  className?: string;
  trail?: boolean;
}) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn("text-[13px] text-ink-2", className)}>
      <ol className="flex flex-wrap items-center gap-x-1.5">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          const current = last && !trail;
          return (
            <Fragment key={`${index}:${item.label}`}>
              <li className="min-w-0">
                {item.href && !current ? (
                  // 44px to tap on phones and tablets (S4).
                  <Link
                    href={item.href}
                    className="inline-flex min-h-11 items-center hover:text-ink hover:underline lg:min-h-0"
                  >
                    {item.label}
                  </Link>
                ) : (
                  <span
                    aria-current={current ? "page" : undefined}
                    className={current ? "text-ink" : ""}
                  >
                    {item.label}
                  </span>
                )}
              </li>
              {!last && (
                <li aria-hidden="true" className="text-ink-3">
                  ›
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}
