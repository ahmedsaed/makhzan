"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef } from "react";

import { chipClass } from "@/components/chips";
import { Link } from "@/components/link";
import { cn } from "@/lib/utils";

/**
 * "Price" in a browse page's toolbar (layout B): a chip that opens a small
 * panel with Min and Max, a GET form, so it works with JavaScript off. A
 * native `<details>`: with JavaScript, Escape and a click elsewhere close it.
 *
 * The panel is positioned against the toolbar's chip row (its nearest
 * positioned ancestor), not the chip, so the chip bar's sideways scrolling
 * never clips it; on opening it is moved under the chip, as far as the row
 * allows (`place`), so on a phone it stays the row's full width. When a price
 * is set the chip is on and names it. An empty Min or Max is left out of the
 * URL rather than sent as `min_price=`.
 */
export function PriceChip({
  action,
  hidden,
  min,
  max,
  label,
  clearHref,
}: {
  action: string;
  /** Every other parameter of the page, carried through the form. */
  hidden: Record<string, string>;
  min?: number;
  max?: number;
  /** The set price in words ("EGP 100 – 500"), or undefined for none. */
  label?: string;
  clearHref: string;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const active = label !== undefined;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && ref.current?.open) {
        ref.current.open = false;
        ref.current.querySelector("summary")?.focus();
      }
    };
    const onClick = (event: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(event.target as Node)) {
        ref.current.open = false;
      }
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    const onResize = () => place(ref.current, form.current);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onClick);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  // An empty field is not sent: `?min_price=&max_price=` says nothing.
  const dropEmpty = (event: React.FormEvent<HTMLFormElement>) => {
    for (const input of event.currentTarget.querySelectorAll("input")) {
      if (input.value === "") input.disabled = true;
    }
  };

  const field =
    "h-11 w-full min-w-0 rounded-md border border-line-strong bg-surface px-3 text-base text-ink placeholder:text-ink-3 sm:h-9 sm:text-sm";
  return (
    <details
      ref={ref}
      data-price-chip
      className="group"
      onToggle={() => place(ref.current, form.current)}
    >
      <summary
        className={cn(
          chipClass(active),
          "cursor-pointer list-none [&::-webkit-details-marker]:hidden",
        )}
      >
        {active && <Check aria-hidden="true" strokeWidth={2.5} className="size-3.5" />}
        {active ? label : "Price"}
        <ChevronDown
          aria-hidden="true"
          className="size-3.5 transition-transform group-open:rotate-180"
        />
      </summary>
      <form
        ref={form}
        onSubmit={dropEmpty}
        action={action}
        method="get"
        aria-label="Price, EGP"
        className="absolute top-full left-0 z-30 mt-2 flex w-72 max-w-full flex-col gap-3 rounded-card border border-line bg-surface p-3"
      >
        {Object.entries(hidden).map(([key, value]) => (
          <input key={key} type="hidden" name={key} value={value} />
        ))}
        <div className="flex gap-2.5">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-ink-2">
            Min, EGP
            <input
              type="number"
              name="min_price"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="0"
              defaultValue={min}
              className={field}
            />
          </label>
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-ink-2">
            Max, EGP
            <input
              type="number"
              name="max_price"
              min={0}
              step="any"
              inputMode="decimal"
              placeholder="Any"
              defaultValue={max}
              className={field}
            />
          </label>
        </div>
        <div className="flex gap-2.5">
          <Link
            href={clearHref}
            className="flex h-11 items-center rounded-control border border-line-strong bg-surface px-4 text-sm text-ink hover:border-ink-3 sm:h-9"
          >
            Clear
          </Link>
          <button
            type="submit"
            className="h-11 flex-1 rounded-control bg-action text-sm font-semibold text-action-ink sm:h-9"
          >
            Apply
          </button>
        </div>
      </form>
    </details>
  );
}

/** The panel under its chip, clamped to the row, which is never wider than the page. */
function place(details: HTMLDetailsElement | null, panel: HTMLFormElement | null) {
  const chip = details?.querySelector("summary");
  const row = panel?.offsetParent;
  if (!details?.open || !panel || !chip || !row) return;
  const rowBox = row.getBoundingClientRect();
  const from = chip.getBoundingClientRect().left - rowBox.left;
  const room = rowBox.width - panel.offsetWidth;
  panel.style.left = `${Math.max(0, Math.min(from, room))}px`;
}
