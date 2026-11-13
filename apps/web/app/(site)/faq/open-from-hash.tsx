"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/** Opens the question with this id, if it is one, and brings it into view. */
function openQuestion(id: string) {
  if (!id) return;
  const target = document.getElementById(id);
  if (!(target instanceof HTMLDetailsElement)) return;
  target.open = true;
  // After the browser's or Next's own scroll, which may have run before the
  // question opened. scroll-mt keeps it clear of the sticky header.
  requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
}

function idFromHash(hash: string) {
  try {
    return decodeURIComponent(hash.slice(1));
  } catch {
    return "";
  }
}

/**
 * Opens the question a link points at (`/faq#price-differs`), however the
 * link was followed:
 *
 * - a full load, or a client-side navigation from another page: on mount,
 *   and again if the path changes under it;
 * - a plain `#id` link, or back and forward: `hashchange` and `popstate`;
 * - a Next `<Link>` to `/faq#id` (any query) from this page: Next pushes the
 *   state itself, which fires no `hashchange`, so a click on any link to this
 *   path with a fragment opens its question.
 *
 * Without JavaScript the browser still scrolls to it, and one tap opens it.
 */
export function OpenFromHash() {
  const pathname = usePathname();

  useEffect(() => {
    openQuestion(idFromHash(window.location.hash));
  }, [pathname]);

  useEffect(() => {
    const fromLocation = () => openQuestion(idFromHash(window.location.hash));
    const onClick = (event: MouseEvent) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (!(anchor instanceof HTMLAnchorElement) || (anchor.target && anchor.target !== "_self")) {
        return;
      }
      const url = new URL(anchor.href, window.location.href);
      if (
        url.origin !== window.location.origin ||
        url.pathname !== window.location.pathname ||
        !url.hash
      ) {
        return;
      }
      openQuestion(idFromHash(url.hash));
    };
    window.addEventListener("hashchange", fromLocation);
    window.addEventListener("popstate", fromLocation);
    document.addEventListener("click", onClick);
    return () => {
      window.removeEventListener("hashchange", fromLocation);
      window.removeEventListener("popstate", fromLocation);
      document.removeEventListener("click", onClick);
    };
  }, []);

  return null;
}
