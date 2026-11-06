import { Clock } from "lucide-react";

import { agoText, daysSince, freshnessTier } from "@/lib/freshness";
import { cn } from "@/lib/utils";

/**
 * When a price was last checked (rule F1), louder as it ages (F2): quiet in
 * `ink-2` for two weeks, `age-muted` to six, then a warning in the warn
 * colours — never in `action`, which means "press this".
 *
 * `now` is a prop so a server-rendered list and its hydrated twin agree on the
 * day count, and so tests can pin it.
 */
export function Freshness({
  lastVerified,
  now,
  compact = false,
  className,
}: {
  lastVerified: Date | null;
  now?: Date;
  /** "checked 74 days ago" even in the warn tier, still in the warn colours:
   *  for a tight spot (the phone bottom bar) on a page that states the full
   *  warning elsewhere, with StaleNote. */
  compact?: boolean;
  className?: string;
}) {
  if (!lastVerified) {
    return <span className={cn("text-ink-3", className)}>check date unknown</span>;
  }
  const days = daysSince(lastVerified, now);
  const tier = freshnessTier(lastVerified, now);

  if (tier === "warn") {
    return (
      <span
        data-freshness="warn"
        className={cn(
          // Allowed to wrap: on a 320px phone it is longer than the line.
          "inline-flex items-center rounded-md border border-warn-line bg-warn px-1.5 font-medium text-warn-ink",
          className,
        )}
      >
        {compact ? `checked ${agoText(days)}` : `Price may be out of date (${days} days)`}
      </span>
    );
  }

  return (
    <span
      data-freshness={tier}
      className={cn(tier === "quiet" ? "text-ink-2" : "text-age-muted", className)}
    >
      checked {agoText(days)}
    </span>
  );
}

/**
 * The warn box for a page that shows one price (product, bottom bar): what is
 * wrong and what to do about it. Renders nothing unless the price is in the
 * warn tier, so a page can place it unconditionally.
 */
export function StaleNote({
  lastVerified,
  now,
  className,
}: {
  lastVerified: Date | null;
  now?: Date;
  className?: string;
}) {
  if (!lastVerified || freshnessTier(lastVerified, now) !== "warn") return null;
  const days = daysSince(lastVerified, now);
  return (
    <div
      role="note"
      className={cn(
        "flex gap-2.5 rounded-control border border-warn-line bg-warn p-3 text-sm leading-snug text-warn-ink",
        className,
      )}
    >
      <Clock aria-hidden="true" className="mt-px size-[18px] shrink-0" />
      <p>
        <strong className="font-semibold">Price may be out of date.</strong>
        {` Last checked ${days} days ago. Confirm it on the shop's page.`}
      </p>
    </div>
  );
}
