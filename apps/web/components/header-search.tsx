"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { SearchField } from "@/components/search-field";

/**
 * The header's field, holding the query being shown on /search so it can be
 * edited rather than retyped. It lives in a shared layout that never sees the
 * page's search params, hence a client component reading them.
 *
 * Keyed on the query: a new search remounts the uncontrolled input with the
 * new value instead of keeping what was typed before.
 */
export function HeaderSearch({ className }: { className?: string }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const q = pathname === "/search" ? (params.get("q") ?? "") : "";
  return <SearchField key={q} compact defaultValue={q} className={className} />;
}
