import { Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import type { ShopReach } from "@/lib/api";
import {
  emailHref,
  formatPhone,
  isReachable,
  reportHref,
  telHref,
  whatsappHref,
} from "@/lib/contact";
import { cn } from "@/lib/utils";

export type ContactKind = "whatsapp" | "phone" | "email" | "map" | "report";

/**
 * A way to reach a shop directly: a `tel:`, `mailto:` or WhatsApp link, or a
 * map link; or, as `report`, an email to makhzan about something wrong. These
 * are not pages of a shop's site, so they carry no `ref=makhzan` (rule P4
 * names them as its exception); `data-contact` says which it is, for tests and
 * styles. Counted like a visit (components/shop-link.tsx), as a "shop-contact"
 * event.
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

/** A text link, 44px to tap on phones (S4) though it reads as a line of text. */
export const TEXT_LINK =
  "inline-flex min-h-11 items-center font-semibold text-link hover:underline lg:min-h-0";

/**
 * "Something wrong? Tell us": an email to makhzan naming the shop, and the
 * product on a product page. Beside every block of contact details, since
 * those are copied by hand and go stale.
 */
export function ReportLink({
  shop,
  shopName,
  product,
  page,
  className,
}: {
  /** The shop's slug, or the first shop's on a page of several. */
  shop: string;
  /** The shop's name, or several, as the subject should name them. */
  shopName: string;
  product?: string;
  /** The page's absolute URL, for the body. */
  page: string;
  className?: string;
}) {
  return (
    <p data-report className={cn("text-[13px] text-ink-2", className)}>
      Something wrong?{" "}
      <ContactLink
        kind="report"
        shop={shop}
        href={reportHref({ shop: shopName, product, page })}
        className={TEXT_LINK}
      >
        Tell us
      </ContactLink>
    </p>
  );
}

const ICONS = { whatsapp: MessageCircle, phone: Phone, email: Mail, map: MapPin, report: Mail };

function linksFor(reach: ShopReach, shopName: string) {
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
      href: emailHref(reach.email),
      label: `Email ${shopName}`,
      text: "Email",
    });
  }
  return links;
}

/**
 * "Contact Volt Corner directly": outlined WhatsApp, "Call 02 2345 6789" and
 * Email buttons, whichever the shop publishes, for the one-shop product page,
 * under "Sold by". Nothing at all when it publishes none. 44px tall (S4).
 */
export function ContactButtons({
  reach,
  shop,
  shopName,
  className,
}: {
  reach: ShopReach | null | undefined;
  shop: string;
  shopName: string;
  className?: string;
}) {
  if (!isReachable(reach)) return null;
  const links = linksFor(reach, shopName);
  if (links.length === 0) return null;
  return (
    <div
      data-contact-links="buttons"
      className={cn("flex flex-wrap items-center gap-2", className)}
    >
      <span className="w-full text-[13px] text-ink-2">Contact {shopName} directly</span>
      {links.map(({ kind, href, label, text }) => {
        const Icon = ICONS[kind];
        return (
          <ContactLink
            key={kind}
            kind={kind}
            shop={shop}
            href={href}
            aria-label={label}
            className="inline-flex h-11 items-center gap-1.5 rounded-control border-[1.5px] border-line-strong bg-surface px-3 text-sm font-semibold whitespace-nowrap text-ink hover:border-link"
          >
            <Icon aria-hidden="true" className="size-4" />
            {text}
          </ContactLink>
        );
      })}
    </div>
  );
}

/**
 * The shops behind a product's offers, once each, with how to reach them:
 * "Nile Parts  Call 19123", "Volt Corner  WhatsApp · Call 02 2345 6789 · Email".
 *
 * Under the offers rather than in them: a shop with three offers would say the
 * same thing three times, and a row that left it out because its neighbour
 * said it would depend on its neighbour (P3). Only shops that publish a way to
 * be reached are listed; nothing at all when none does.
 */
export function ShopContactList({
  shops,
  className,
}: {
  shops: { slug: string; name: string; reach: ShopReach | null | undefined }[];
  className?: string;
}) {
  const reachable = shops.flatMap((shop) =>
    isReachable(shop.reach) ? [{ ...shop, links: linksFor(shop.reach, shop.name) }] : [],
  );
  if (!reachable.some((shop) => shop.links.length > 0)) return null;
  return (
    <section
      data-contact-links="shops"
      aria-labelledby="shop-contacts-heading"
      className={className}
    >
      <h3 id="shop-contacts-heading" className="text-[15px] text-ink">
        Contact the shops
      </h3>
      <ul className="mt-1 text-[13px]">
        {reachable.map(({ slug, name, links }) => (
          <li
            key={slug}
            data-shop-contact-line={slug}
            className="flex flex-wrap items-center gap-x-3 border-b border-line py-1 last:border-b-0 lg:py-1.5"
          >
            <span className="me-auto font-semibold text-ink">{name}</span>
            {links.map(({ kind, href, label, text }) => {
              const Icon = ICONS[kind];
              return (
                <ContactLink
                  key={kind}
                  kind={kind}
                  shop={slug}
                  href={href}
                  aria-label={label}
                  className={cn(TEXT_LINK, "gap-1 whitespace-nowrap")}
                >
                  <Icon aria-hidden="true" className="size-3.5" />
                  {text}
                </ContactLink>
              );
            })}
          </li>
        ))}
      </ul>
    </section>
  );
}
