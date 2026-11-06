import type { ComponentProps } from "react";

import { shopUrl } from "@/lib/shop-url";

/**
 * A link to a shop's own page — the only link out of makhzan (rule P4).
 *
 * It carries `ref=makhzan` so the shop can count us, and an Umami event so we
 * can count them: "we sent you N visitors" is said with numbers or not at all.
 * Umami's tracker picks the event up from the `data-umami-event*` attributes on
 * click, with no JavaScript of ours; when the tracker is not loaded (dev, CI)
 * they are inert.
 *
 * `noopener` without `noreferrer`: the shop seeing makhzan as the referrer is
 * the point.
 */
export function ShopLink({
  href,
  shop,
  children,
  ...props
}: Omit<ComponentProps<"a">, "href" | "target" | "rel"> & {
  /** The shop's URL as crawled. `ref=makhzan` is added here. */
  href: string;
  /** The shop's slug, recorded with the click. */
  shop: string;
}) {
  return (
    <a
      {...props}
      href={shopUrl(href)}
      target="_blank"
      rel="noopener"
      data-umami-event="shop-click"
      data-umami-event-shop={shop}
    >
      {children}
    </a>
  );
}
