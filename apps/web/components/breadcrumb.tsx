import { Fragment } from "react";

import { Link } from "@/components/link";
import { cn } from "@/lib/utils";

export type Crumb = { label: string; href?: string };

/**
 * Trade › group › category. The last crumb is the current page and is not a
 * link; any crumb without an href is plain text too.
 */
export function Breadcrumb({ items, className }: { items: Crumb[]; className?: string }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb" className={cn("text-[13px] text-ink-2", className)}>
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
        {items.map((item, index) => {
          const last = index === items.length - 1;
          return (
            <Fragment key={`${index}:${item.label}`}>
              <li className="min-w-0">
                {item.href && !last ? (
                  <Link href={item.href} className="hover:text-ink hover:underline">
                    {item.label}
                  </Link>
                ) : (
                  <span aria-current={last ? "page" : undefined} className={last ? "text-ink" : ""}>
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
