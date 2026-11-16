"use client";

import { Popover } from "@base-ui/react/popover";

import { AI_EXPLAINED, AI_LABEL, AI_TITLE } from "@/lib/shop-view";
import { cn } from "@/lib/utils";

/**
 * Lucide's "sparkles", inline: the AI mark. Drawn here rather than imported so
 * the pill, the tab and the report form share one 12px glyph.
 */
export function Sparkles({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      data-sparkles
      className={cn("size-3 shrink-0", className)}
    >
      <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z" />
      <path d="M20 3v4" />
      <path d="M22 5h-4" />
      <path d="M4 17v2" />
      <path d="M5 18H3" />
    </svg>
  );
}

/** The pill itself: a neutral outline (never the `badge` colours, which mean
 *  "N shops"), the sparkles and "AI". */
const PILL =
  "inline-flex h-5 shrink-0 items-center gap-[3px] rounded-full border border-line-strong bg-surface ps-[5px] pe-1.5 text-[11px] leading-none font-semibold text-ink-2";

/**
 * "Matched by AI" on an offer's row: a button named for what it means, whose
 * popover says why it is there and what to do. Hover (or focus) opens it on a
 * pointer, a tap on a touch screen, Enter or Space on a keyboard; Esc, a tap
 * elsewhere or moving away closes it. The popover sits in a portal, so the
 * offers list's rounded, clipped box cannot cut it off. The tap area reaches
 * 44px tall around the 20px pill (S4).
 */
export function AiBadge({ className }: { className?: string }) {
  return (
    <Popover.Root>
      <Popover.Trigger
        openOnHover
        delay={150}
        data-ai-badge
        aria-label={AI_LABEL}
        className={cn(
          PILL,
          "relative cursor-help outline-offset-2 outline-link focus-visible:outline-2",
          "after:absolute after:-inset-x-2 after:-inset-y-3.5 after:content-['']",
          className,
        )}
      >
        <Sparkles />
        <span aria-hidden="true">AI</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="top" sideOffset={8} collisionPadding={16} className="z-40">
          <Popover.Popup
            data-ai-tip
            // Information only: focus stays on the badge, so Esc and Tab carry on from it.
            initialFocus={false}
            className="w-[min(240px,calc(100vw-32px))] rounded-[10px] bg-ink px-2.5 py-2 text-start text-[12.5px] leading-snug font-normal text-ground outline-none"
          >
            <Popover.Title className="mb-0.5 block text-[12.5px] font-semibold">
              {AI_TITLE}
            </Popover.Title>
            <Popover.Description>{AI_EXPLAINED}</Popover.Description>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

/**
 * The same pill, not interactive: on a "What the shops say" tab (a label for
 * a radio, which must not hold a button) and in the report form. Hidden from
 * screen readers, which hear "matched by AI" in the label beside it; a pointer
 * gets the explanation as its tooltip.
 */
export function AiPill({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-ai-pill
      title={`${AI_TITLE}. ${AI_EXPLAINED}`}
      className={cn(PILL, className)}
    >
      <Sparkles />
      AI
    </span>
  );
}
