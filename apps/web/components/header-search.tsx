"use client";

import { usePathname, useSearchParams } from "next/navigation";

import { SearchField } from "@/components/search-field";

/**
 * The header's field, holding the query being shown on /search so it can be
 * edited rather than retyped. It lives in a shared layout that never sees the
 * page's search params, hence a client component reading them.
 *
 * On a shop's page, or a search inside one shop, it searches that shop: a
 * visitor who has narrowed to a shop and types a new part number means "in
 * this shop" too. The scope is a visible, checked "This shop only" box, so
 * unticking it searches every shop, with JavaScript or without.
 *
 * Keyed on the query and the shop: a new search remounts the uncontrolled
 * input with the new value instead of keeping what was typed before.
 */
export function HeaderSearch({ className }: { className?: string }) {
  const pathname = usePathname();
  const params = useSearchParams();
  const onSearch = pathname === "/search";
  const q = onSearch ? (params.get("q") ?? "") : "";
  const shop = onSearch ? params.get("shop") : shopOfPath(pathname);
  return (
    <SearchField
      key={`${shop ?? ""}:${q}`}
      compact
      defaultValue={q}
      scopeToggle={shop ? { name: "shop", value: shop, label: "This shop only" } : undefined}
      className={className}
    />
  );
}

/** `/shops/shop-a` → `shop-a`; anything else → null. */
function shopOfPath(pathname: string): string | null {
  const match = /^\/shops\/([^/]+)\/?$/.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}
