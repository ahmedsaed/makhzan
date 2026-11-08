/**
 * Product icons scattered over the top of every page, fading out downward
 * (globals.css, `.bg-pattern`; the tiles are drawn by scripts/pattern-tile.mjs).
 *
 * Decoration only: hidden from assistive technology, never in the way of a
 * click, and behind everything. The outer layer is the page's full height and
 * clips, so a page shorter than the fade is not made longer by it; the inner one
 * is the fade itself. Absolute, not fixed: it scrolls away with the top of the
 * page.
 */
export function BackgroundPattern() {
  return (
    <div
      aria-hidden="true"
      data-bg-pattern
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
    >
      <div className="bg-pattern" />
    </div>
  );
}
