/**
 * The list/grid choice, remembered per visitor in localStorage.
 *
 * A small external store rather than React context, so the toggle in a
 * toolbar and the list further down agree without a provider wrapped around
 * both. The server always renders the list — it cannot know the choice — and
 * `useSyncExternalStore` swaps in the stored view after hydration without a
 * mismatch warning.
 *
 * Every storage access is guarded: a private window, blocked site data or a
 * full quota throws, and a broken preference must never break the results.
 */

export type ResultView = "list" | "grid";

const KEY = "makhzan:view";
const EVENT = "makhzan:view";

/** The choice made on this page, which also covers storage refusing to keep it. */
let memory: ResultView | null = null;

export function readView(): ResultView {
  try {
    return window.localStorage.getItem(KEY) === "grid" ? "grid" : "list";
  } catch {
    return "list";
  }
}

export function writeView(view: ResultView): void {
  try {
    window.localStorage.setItem(KEY, view);
  } catch {
    // Not remembered, but still applied for this page below.
  }
  // Applied even when storage failed, through a variable the store reads first.
  memory = view;
  window.dispatchEvent(new Event(EVENT));
}

export function currentView(): ResultView {
  return memory ?? readView();
}

export function serverView(): ResultView {
  return "list";
}

export function subscribeView(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === KEY) {
      memory = null;
      onChange();
    }
  };
  window.addEventListener(EVENT, onChange);
  // Another tab changed it.
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}
