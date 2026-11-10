import { Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import type { ShopReach } from "@/lib/api";
import { formatPhone, isReachable, mailtoHref, telHref, whatsappHref } from "@/lib/contact";
import { cn } from "@/lib/utils";

export type ContactKind = "whatsapp" | "phone" | "email" | "map";

/**
 * A way to reach a shop directly: a `tel:`, `mailto:` or WhatsApp link, or the
 * shop's own map link. These are the shop's own published routes, not pages of
 * its site, so they carry no `ref=makhzan` (rule P4 names them as the
 * exception); `data-contact` says which it is, for tests and styles. Counted
 * like a visit (components/shop-link.tsx), as a "shop-contact" event.
 */
export function ContactLink({
  kind,
  shop,
  href,
  children,
  ...props
}: Omit<ComponentProps<"a">, "href" | "target" | "rel"> & {
  kind: ContactKind;
  shop: string;
  href: string;
  children: ReactNode;
}) {
  // WhatsApp and maps open a page; a call or an email opens an app in place.
  const external = kind === "whatsapp" || kind === "map";
  return (
    <a
      {...props}
      href={href}
      data-contact={kind}
      {...(external ? { target: "_blank", rel: "noopener" } : {})}
      data-umami-event="shop-contact"
      data-umami-event-shop={shop}
      data-umami-event-via={kind}
    >
      {children}
    </a>
  );
}

/**
 * "WhatsApp · Call 02 2345 6789 · Email" for one offer's shop: the shop's own
 * first number, WhatsApp and email, whichever it publishes. Nothing at all when
 * it publishes none.
 *
 * `inline` is a line of text links, for an offer row, where it must not crowd
 * the price and View; `buttons` is a row of outlined buttons, for the one-shop
 * product page, where it sits under "Sold by". Both 44px to tap on phones (S4).
 */
export function ContactLinks({
  reach,
  shop,
  shopName,
  variant,
  className,
}: {
  reach: ShopReach | null | undefined;
  shop: string;
  shopName: string;
  variant: "inline" | "buttons";
  className?: string;
}) {
  if (!isReachable(reach)) return null;
  const links: { kind: ContactKind; href: string; label: string; text: string }[] = [];
  const whatsapp = reach.whatsapp ? whatsappHref(reach.whatsapp) : null;
  if (whatsapp) {
    links.push({
      kind: "whatsapp",
      href: whatsapp,
      label: `WhatsApp ${shopName}`,
      text: "WhatsApp",
    });
  }
  const tel = reach.phone ? telHref(reach.phone) : null;
  if (reach.phone && tel) {
    const number = formatPhone(reach.phone);
    links.push({
      kind: "phone",
      href: tel,
      label: `Call ${shopName} on ${number}`,
      text: `Call ${number}`,
    });
  }
  if (reach.email) {
    links.push({
      kind: "email",
      href: mailtoHref(reach.email),
      label: `Email ${shopName}`,
      text: "Email",
    });
  }
  if (links.length === 0) return null;

  const icons = { whatsapp: MessageCircle, phone: Phone, email: Mail, map: MapPin };
  return (
    <div
      data-contact-links={variant}
      className={cn(
        variant === "inline"
          ? "flex flex-wrap items-center gap-x-3 text-[13px]"
          : "flex flex-wrap items-center gap-2",
        className,
      )}
    >
      {variant === "inline" ? (
        <span className="text-ink-2">Contact:</span>
      ) : (
        <span className="w-full text-[13px] text-ink-2">Contact {shopName} directly</span>
      )}
      {links.map(({ kind, href, label, text }) => {
        const Icon = icons[kind];
        return (
          <ContactLink
            key={kind}
            kind={kind}
            shop={shop}
            href={href}
            aria-label={label}
            className={
              variant === "inline"
                ? "inline-flex min-h-11 items-center gap-1 font-semibold whitespace-nowrap text-link hover:underline lg:min-h-0"
                : "inline-flex h-11 items-center gap-1.5 rounded-control border-[1.5px] border-line-strong bg-surface px-3 text-sm font-semibold whitespace-nowrap text-ink hover:border-link"
            }
          >
            <Icon aria-hidden="true" className={variant === "inline" ? "size-3.5" : "size-4"} />
            {text}
          </ContactLink>
        );
      })}
    </div>
  );
}
