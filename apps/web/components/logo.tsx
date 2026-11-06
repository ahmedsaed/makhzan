import { MARK } from "@/lib/brand";
import { cn } from "@/lib/utils";

/**
 * The mark: a 2×2 parts organizer, three compartments outlined and one filled
 * (docs/DESIGN.md, "Brand"). The outline is `currentColor`, so it takes the
 * ink of whatever it sits in and follows the theme; the fill is the `brand`
 * token. Decorative: whatever contains it carries the name.
 *
 * The viewBox is cropped to the drawing (the outline's outer edge, at 2.25),
 * so the box measures the mark itself and sizes in `em` line up with text.
 */
export function LogoMark({ className }: { className?: string }) {
  const { size, radius, stroke } = MARK;
  return (
    <svg
      viewBox="2 2 44 44"
      aria-hidden="true"
      focusable="false"
      className={cn("shrink-0", className)}
    >
      {MARK.outlined.map(({ x, y }) => (
        <rect
          key={`${x}-${y}`}
          x={x}
          y={y}
          width={size}
          height={size}
          rx={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
        />
      ))}
      <rect
        x={MARK.filled.x}
        y={MARK.filled.y}
        width={size}
        height={size}
        rx={radius}
        className="fill-brand"
      />
    </svg>
  );
}

/**
 * Mark and wordmark. Sized by its font size: the mark is 1.2em, about the
 * wordmark's cap height plus its x-height in Archivo (0.69 + 0.53), so one
 * `text-[…]` scales both together.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span
      data-logo
      className={cn(
        "inline-flex items-center gap-[0.36em] font-display leading-none font-extrabold tracking-[-0.02em] text-ink",
        className,
      )}
    >
      <LogoMark className="size-[1.2em]" />
      <span>makhzan</span>
    </span>
  );
}
