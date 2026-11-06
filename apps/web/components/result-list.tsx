"use client";

import { LayoutGrid, List } from "lucide-react";
import { useSyncExternalStore } from "react";

import { ResultCard, ResultRow } from "@/components/result";
import type { SearchHit } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  currentView,
  serverView,
  subscribeView,
  writeView,
  type ResultView,
} from "@/lib/view-preference";

function useResultView(): ResultView {
  return useSyncExternalStore(subscribeView, currentView, serverView);
}

/**
 * Results as rows or cards, whichever the visitor last chose. Rows on the
 * server and with JavaScript off: rows compare better, and the list must work
 * before anything hydrates.
 *
 * `now` should be taken once on the server and passed down, so the server's
 * "checked 14 days ago" and the browser's agree across a midnight.
 */
export function ResultList({
  hits,
  now,
  hideShop,
  className,
}: {
  hits: SearchHit[];
  /** The server render's clock. A Date crosses the server/client boundary
   *  intact, so the hydrated list counts days from the same instant. */
  now?: Date;
  /** The page is one shop's own: results leave its name out (see ResultRow). */
  hideShop?: boolean;
  className?: string;
}) {
  const view = useResultView();

  if (view === "grid") {
    return (
      <ul
        data-view="grid"
        className={cn(
          "grid grid-cols-2 gap-2.5 px-4 sm:grid-cols-3 md:px-0 lg:grid-cols-4 xl:grid-cols-5",
          className,
        )}
      >
        {hits.map((hit, index) => (
          <ResultCard key={hit.id} hit={hit} now={now} priority={index < 4} hideShop={hideShop} />
        ))}
      </ul>
    );
  }
  return (
    <ul data-view="list" className={cn("border-t border-line bg-surface", className)}>
      {hits.map((hit, index) => (
        <ResultRow key={hit.id} hit={hit} now={now} priority={index < 3} hideShop={hideShop} />
      ))}
    </ul>
  );
}

/**
 * The list/grid switch. Two buttons in one group, the active one filled with
 * `chip-on`, as in the toolbar of every results page.
 */
export function ViewToggle({ className }: { className?: string }) {
  const view = useResultView();
  return (
    <div
      role="group"
      aria-label="View"
      className={cn("flex overflow-hidden rounded-md border border-line-strong", className)}
    >
      <ViewButton label="List view" active={view === "list"} onClick={() => writeView("list")}>
        <List className="size-4" aria-hidden="true" />
      </ViewButton>
      <ViewButton label="Grid view" active={view === "grid"} onClick={() => writeView("grid")}>
        <LayoutGrid className="size-4" aria-hidden="true" />
      </ViewButton>
    </div>
  );
}

function ViewButton({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        // 44px tall on phones (S4), the toolbar's 36px from `sm`.
        "grid h-11 w-11 place-items-center sm:h-9 sm:w-9",
        active ? "bg-chip-on text-chip-on-ink" : "bg-surface text-ink-2 hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
