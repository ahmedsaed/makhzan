import { Package, type LucideIcon } from "lucide-react";

import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A group or category on a trade page. On a phone it is the object tile
 * (components/object-tile.tsx): a square frame with the name under it, five
 * to a row. From `lg` the same link turns on its side — a small frame, the
 * name, its count and what is inside — because a row of eight big squares
 * holding the same stand-in icon is most of a desktop screen saying nothing.
 *
 * One element at every width, so a tile is never in the page twice.
 */
export function BrowseTile({
  href,
  label,
  image = null,
  icon: Icon = Package,
  count,
  hint,
  current = false,
  size = "md",
}: {
  href: string;
  label: string;
  image?: string | null;
  icon?: LucideIcon;
  /** Shown at every width on `sm` tiles, from `lg` on `md` ones. */
  count?: number;
  /** What is inside, in words; from `lg` only, where there is room. */
  hint?: string;
  current?: boolean;
  /** `md` for groups, `sm` for the denser category tiles. */
  size?: "md" | "sm";
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "true" : undefined}
      className={cn(
        "group flex h-full flex-col gap-1.5 text-ink",
        "lg:flex-row lg:items-center lg:gap-3 lg:rounded-control lg:bg-surface lg:p-2",
        current
          ? "lg:outline-2 lg:-outline-offset-2 lg:outline-chip-on"
          : "lg:border lg:border-line lg:hover:border-line-strong",
      )}
    >
      <span
        className={cn(
          "relative block aspect-square w-full shrink-0 overflow-hidden bg-photo-frame",
          size === "sm" ? "rounded-md lg:size-9" : "rounded-control lg:size-11 lg:rounded-md",
          current
            ? "border-2 border-chip-on lg:border lg:border-line"
            : "border border-line group-hover:border-line-strong",
        )}
      >
        {image ? (
          <PhotoFrame src={image} alt="" className="rounded-none border-0" />
        ) : (
          // ink-3 reads on the white frame in both themes, as the part glyph does.
          <Icon
            aria-hidden="true"
            strokeWidth={1.25}
            className="absolute inset-0 m-auto size-1/2 text-ink-3 lg:size-3/5"
          />
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span
          className={cn(
            // Hyphenated rather than broken anywhere: "Transmis-sion", not "Transmissi on".
            "leading-tight break-words hyphens-auto lg:text-left lg:text-sm lg:hyphens-none",
            size === "sm" ? "text-xs" : "text-center text-[11px] sm:text-[13px] lg:font-semibold",
            current ? "font-semibold" : "font-normal",
          )}
        >
          {label}
          {count !== undefined && (
            <>
              {" "}
              <span
                className={cn(
                  "font-normal text-ink-3 tabular",
                  size === "md" && "hidden lg:inline",
                )}
              >
                {formatCount(count)}
              </span>
            </>
          )}
        </span>
        {hint && (
          <span className="hidden truncate text-xs leading-snug text-ink-2 lg:block">{hint}</span>
        )}
      </span>
    </Link>
  );
}

/**
 * Columns for a row of tiles from `lg`: as many as fit, but balanced, so
 * eight tiles are two rows of four rather than six and a lonely two.
 */
export function balancedColumns(count: number, max: number): number {
  if (count <= 0) return 1;
  const rows = Math.ceil(count / max);
  return Math.ceil(count / rows);
}
