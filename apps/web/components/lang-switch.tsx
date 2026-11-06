"use client";

import { Link } from "@/components/link";
import { usePathname, useSearchParams } from "next/navigation";

import type { Lang } from "@/lib/i18n";
import { switchLangPath } from "@/lib/routes";

/**
 * Links to the same page in the other language, query string and all — losing
 * a search because you switched language is the bug this avoids.
 *
 * A link, not a toggle: the other language is a different URL, so it has to be
 * something a browser can follow and a crawler can see.
 */
export function LangSwitch({ lang }: { lang: Lang }) {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const other: Lang = lang === "en" ? "ar" : "en";
  const href = `${switchLangPath(pathname, other)}${search ? `?${search}` : ""}`;

  return (
    <Link
      href={href}
      hrefLang={other}
      aria-label={other === "ar" ? "التبديل إلى العربية" : "Switch to English"}
      className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-rule text-xs font-medium text-ink-muted hover:bg-chip hover:text-ink"
    >
      {other === "ar" ? "ع" : "EN"}
    </Link>
  );
}
