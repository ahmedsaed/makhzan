"use client";

import { useEffect } from "react";

/**
 * Opens the question a link points at (`/faq#price-differs`), on arrival and
 * when the hash changes. Without JavaScript the browser still scrolls to it,
 * and one tap opens it.
 */
export function OpenFromHash() {
  useEffect(() => {
    const open = () => {
      const id = decodeURIComponent(window.location.hash.slice(1));
      if (!id) return;
      const target = document.getElementById(id);
      if (target instanceof HTMLDetailsElement) target.open = true;
    };
    open();
    window.addEventListener("hashchange", open);
    return () => window.removeEventListener("hashchange", open);
  }, []);
  return null;
}
