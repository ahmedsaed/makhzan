import { Check } from "lucide-react";

import { Link } from "@/components/link";
import { cn } from "@/lib/utils";

/**
 * A toggle chip that is a link, not a button: pressing it navigates to the
 * same page with one query parameter set or removed (build the href with
 * `withParams` from lib/routes). Every filter state is then a URL — shareable,
 * reachable with the back button, and working with JavaScript off.
 *
 * `active` is the page's reading of the URL, not the chip's own state: "In
 * stock" is on by default, so it is active when its parameter is *absent*,
 * and only the page knows that.
 */
export function Chip({
  href,
  active,
  children,
  className,
}: {
  href: string;
  active: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      // A link cannot be aria-pressed; "current" is the nearest honest state
      // for a link that represents the filter this page is showing.
      aria-current={active ? "true" : undefined}
      data-active={active || undefined}
      className={cn(chipClass(active), className)}
    >
      {active && <Check aria-hidden="true" strokeWidth={2.5} className="size-3.5" />}
      {children}
    </Link>
  );
}

/** The chip look, for anything that must sit in a chip bar without being a
 *  Chip — the filter sheet's trigger is a `<summary>`. */
export function chipClass(active = false): string {
  return cn(
    // 36px drawn, 44px tappable (S4): an invisible 4px extension above and
    // below, which the chip bar's own padding leaves room for.
    "relative inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm whitespace-nowrap after:absolute after:inset-x-0 after:-inset-y-1 after:content-['']",
    active
      ? "border-chip-on bg-chip-on text-chip-on-ink"
      : "border-line-strong bg-surface text-ink hover:border-ink-3",
  );
}

/** A row of chips. Scrolls sideways inside itself on a narrow phone rather
 *  than pushing the page wider (S4). */
export function ChipBar({
  label = "Quick filters",
  children,
  className,
}: {
  label?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <nav
      aria-label={label}
      className={cn(
        "-my-1 flex [scrollbar-width:none] items-center gap-2 overflow-x-auto py-1",
        className,
      )}
    >
      {children}
    </nav>
  );
}
