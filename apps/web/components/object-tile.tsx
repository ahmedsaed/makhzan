import { Link } from "@/components/link";
import { PhotoFrame } from "@/components/photo-frame";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A trade, group or category shown as one iconic object: a photo, its name,
 * and how many products it holds. McMaster-Carr's device — a photo of a thing
 * is recognised faster than its name is read, and a category name alone
 * ("Fasteners") rarely says what is inside.
 *
 * `hint` is the line that does say it ("O-rings, bearings, oil seals").
 * `current` marks the selected group on a trade page.
 */
export function ObjectTile({
  href,
  label,
  image = null,
  count,
  hint,
  current = false,
  size = "md",
  className,
}: {
  href: string;
  label: string;
  /** A representative product photo; the part glyph stands in without one. */
  image?: string | null;
  count?: number;
  hint?: string;
  current?: boolean;
  /** `md` for groups and trades, `sm` for the denser category tiles. */
  size?: "md" | "sm";
  className?: string;
}) {
  return (
    <Link
      href={href}
      aria-current={current ? "true" : undefined}
      className={cn(
        "flex h-full flex-col gap-2 rounded-card border bg-surface p-2.5 hover:border-line-strong",
        current ? "border-chip-on" : "border-line",
        className,
      )}
    >
      <PhotoFrame src={image} alt="" className={size === "sm" ? "rounded-md" : undefined} />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span
          className={cn(
            "leading-tight font-semibold text-ink",
            size === "sm" ? "text-[13px]" : "text-sm",
          )}
        >
          {label}
          {count !== undefined && (
            <span className="tabular ms-1.5 font-normal text-ink-3">{formatCount(count)}</span>
          )}
        </span>
        {hint && <span className="line-clamp-2 text-xs leading-snug text-ink-2">{hint}</span>}
      </span>
    </Link>
  );
}
