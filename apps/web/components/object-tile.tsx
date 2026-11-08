import { Package, type LucideIcon } from "lucide-react";

import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A department, group or category shown as one iconic object: a photo, its name,
 * and how many products it holds. McMaster-Carr's device — a photo of a thing
 * is recognised faster than its name is read, and a category name alone
 * ("Fasteners") rarely says what is inside.
 *
 * The frame leads and the name sits under it, so a row of five still fits a
 * phone. `hint` is the line that says what is inside ("O-rings, bearings, oil
 * seals"). `current` marks the selected group or category on a department page.
 */
export function ObjectTile({
  href,
  label,
  image = null,
  icon: Icon = Package,
  count,
  hint,
  current = false,
  size = "md",
  className,
}: {
  href: string;
  label: string;
  /** A representative product photo; `icon` stands in without one. */
  image?: string | null;
  /** A neutral line icon for when there is no photo yet. */
  icon?: LucideIcon;
  count?: number;
  hint?: string;
  current?: boolean;
  /** `md` for groups and departments, `sm` for the denser category tiles. */
  size?: "md" | "sm";
  className?: string;
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "true" : undefined}
      className={cn("group flex h-full flex-col gap-1.5 text-ink", className)}
    >
      <span
        className={cn(
          "relative block aspect-square w-full overflow-hidden bg-photo-frame",
          size === "sm" ? "rounded-md" : "rounded-control",
          current ? "border-2 border-chip-on" : "border border-line group-hover:border-line-strong",
        )}
      >
        {image ? (
          <PhotoFrame src={image} alt="" className="rounded-none border-0" />
        ) : (
          // ink-3 reads on the white frame in both themes, as the part glyph does.
          <Icon
            aria-hidden="true"
            strokeWidth={1.25}
            className="absolute inset-0 m-auto size-1/2 text-ink-3"
          />
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span
          className={cn(
            // Hyphenated rather than broken anywhere: "Transmis-sion", not "Transmissi on".
            "leading-tight break-words hyphens-auto",
            size === "sm" ? "text-xs" : "text-center text-[11px] sm:text-[13px]",
            current ? "font-semibold" : "font-normal",
          )}
        >
          {label}
          {count !== undefined && (
            <>
              {" "}
              <span className="font-normal text-ink-3 tabular">{formatCount(count)}</span>
            </>
          )}
        </span>
        {hint && <span className="line-clamp-2 text-xs leading-snug text-ink-2">{hint}</span>}
      </span>
    </Link>
  );
}
