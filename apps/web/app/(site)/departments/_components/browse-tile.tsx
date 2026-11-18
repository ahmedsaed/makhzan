import { Package } from "lucide-react";

import { CategoryIcon, type TileIcon } from "@/components/category-icons";
import { chipClass } from "@/components/chips";
import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A group on a department page. On a phone it is the object tile
 * (components/object-tile.tsx): a square frame with the name under it, five
 * to a row. From `lg` the same link turns on its side — a small frame, the
 * name, its count and what is inside — because a row of eight big squares
 * holding the same stand-in icon is most of a desktop screen saying nothing.
 *
 * Groups are tiles and categories are chips (CategoryChip, ShortcutPill), so
 * the two never look alike: the icon pilot found a group could not be told
 * from a category when both were tiles.
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
}: {
  href: string;
  label: string;
  image?: string | null;
  icon?: TileIcon;
  /** From `lg`, where there is room. */
  count?: number;
  /** What is inside, in words; from `lg` only. */
  hint?: string;
  current?: boolean;
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
          "relative block aspect-square w-full shrink-0 overflow-hidden rounded-control bg-photo-frame lg:size-11 lg:rounded-md",
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
            "text-center text-[11px] leading-tight break-words hyphens-auto sm:text-[13px] lg:text-left lg:text-sm lg:font-semibold lg:hyphens-none",
            current ? "font-semibold" : "font-normal",
          )}
        >
          {label}
          {count !== undefined && (
            <>
              {" "}
              <span className="hidden font-normal text-ink-3 tabular lg:inline">
                {formatCount(count)}
              </span>
            </>
          )}
        </span>
        {hint && (
          <span className="hidden text-xs leading-snug text-pretty text-ink-2 lg:block">
            {hint}
          </span>
        )}
      </span>
    </Link>
  );
}

/**
 * A category inside the selected group: the site's chip (components/chips.tsx)
 * with the category's icon, when its department has a drawn set, its name and
 * its count. The chips wrap onto more rows rather than scrolling sideways; a
 * long name wraps inside its chip at 320px rather than widening the page (S4).
 */
export function CategoryChip({
  href,
  iconRef,
  label,
  count,
  current = false,
  withIcon,
}: {
  href: string;
  /** The category's ref, which keys its icon. */
  iconRef: string;
  label: string;
  count: number;
  current?: boolean;
  /** False for a department whose set is not drawn yet: a plain chip. */
  withIcon: boolean;
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      data-category-chip={iconRef}
      className={cn(
        chipClass(current),
        "h-auto min-h-9 max-w-full flex-wrap gap-x-1.5 gap-y-0 py-1 whitespace-normal",
      )}
    >
      {withIcon && (
        <CategoryIcon
          iconRef={iconRef}
          className={cn("size-[18px] shrink-0", current ? "text-chip-on-ink" : "text-ink-2")}
        />
      )}
      <span className="whitespace-nowrap">{label}</span>{" "}
      <span
        className={cn("whitespace-nowrap tabular", current ? "text-chip-on-ink" : "text-ink-3")}
      >
        {formatCount(count)}
      </span>
    </Link>
  );
}

/**
 * A "Biggest in {department}" shortcut: a light pill reading "Category · Group
 * count", lighter than a chip and nothing like a group tile, so a shortcut is
 * never mistaken for a group. 32px drawn; the invisible extension above and
 * below makes it 44px to a finger (S4), which is why rows of them sit 12px apart.
 */
export function ShortcutPill({
  href,
  iconRef,
  label,
  group,
  count,
  withIcon,
}: {
  href: string;
  iconRef: string;
  label: string;
  /** The group it sits in, so the shortcut says where it leads. */
  group: string | null;
  count: number;
  withIcon: boolean;
}) {
  return (
    <Link
      href={href}
      data-shortcut={iconRef}
      className={cn(
        "relative inline-flex min-h-8 max-w-full flex-wrap items-center gap-x-1.5 rounded-[18px] border border-line px-3 py-1 text-[13px] text-ink hover:border-line-strong",
        "after:absolute after:inset-x-0 after:-inset-y-[7px] after:content-['']",
      )}
    >
      {withIcon && <CategoryIcon iconRef={iconRef} className="size-4 shrink-0 text-ink-3" />}
      <span className="whitespace-nowrap">{label}</span>{" "}
      {group && <span className="whitespace-nowrap text-ink-3">· {group}</span>}{" "}
      <span className="flex items-center whitespace-nowrap text-ink-3 tabular">
        <span aria-hidden="true" className="mr-2 ml-0.5 h-3 w-px bg-line-strong" />
        {formatCount(count)}
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
