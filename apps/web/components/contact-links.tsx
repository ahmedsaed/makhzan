import { Clock, Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

import { Dotted, INLINE_LINK } from "@/components/dotted";
import type { ShopReach } from "@/lib/api";
import {
  emailHref,
  formatPhone,
  isReachable,
  reportHref,
  telHref,
  whatsappHref,
} from "@/lib/contact";
import { formatOpeningHours } from "@/lib/hours";
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

/** An outlined contact button: 44px on phones (S4), a little tighter from `lg`. */
const BUTTON =
  "inline-flex h-11 items-center gap-1.5 rounded-control border-[1.5px] border-line-strong bg-surface px-3 text-sm font-semibold whitespace-nowrap text-ink hover:border-link lg:h-9";

/** "Something wrong? Tell us", inline: for a line that says something else first. */
export function ReportText({
  shop,
  shopName,
  product,
  page,
  linkClassName = TEXT_LINK,
}: {
  shop: string;
  shopName: string;
  product?: string;
  page: string;
  linkClassName?: string;
}) {
  return (
    <span data-report>
      Something wrong?{" "}
      <ContactLink
        kind="report"
        shop={shop}
        href={reportHref({ shop: shopName, product, page })}
        className={linkClassName}
      >
        Tell us
      </ContactLink>
    </span>
  );
}

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
    <p className={cn("text-[13px] text-ink-2", className)}>
      <ReportText shop={shop} shopName={shopName} product={product} page={page} />
    </p>
  );
}

/**
 * Opening hours on one line, after a clock: "Sat–Thu 10:00–20:30 · Fri
 * 14:00–20:00" (lib/hours.ts). Hand-written hours read as written. Nothing for
 * a shop whose hours nobody has found.
 */
export function HoursLine({ hours, className }: { hours: string[]; className?: string }) {
  const phrases = formatOpeningHours(hours);
  if (phrases.length === 0) return null;
  return (
    <div data-opening-hours className={cn("flex gap-2 text-ink-2", className)}>
      <Clock aria-hidden="true" className="mt-[3px] size-3.5 shrink-0 text-ink-2" />
      <span className="sr-only">Opening hours: </span>
      <Dotted className="min-w-0 flex-1">
        {phrases.map((phrase) => (
          <span key={phrase} dir="auto">
            {phrase}
          </span>
        ))}
      </Dotted>
    </div>
  );
}

const ICONS = { whatsapp: MessageCircle, phone: Phone, email: Mail, map: MapPin, report: Mail };

type Action = { kind: ContactKind; href: string; label: string; text: string };

/**
 * A shop's ways to be reached, in the order a buyer reaches for them: a call
 * (its first number), WhatsApp, email. The same order on the shop page and on
 * a product page.
 */
export function contactActions(
  {
    phone,
    whatsapp,
    email,
  }: { phone: string | null; whatsapp: string | null; email: string | null },
  shopName: string,
): Action[] {
  const actions: Action[] = [];
  const tel = phone ? telHref(phone) : null;
  if (phone && tel) {
    const number = formatPhone(phone);
    actions.push({
      kind: "phone",
      href: tel,
      label: `Call ${shopName} on ${number}`,
      text: `Call ${number}`,
    });
  }
  const chat = whatsapp ? whatsappHref(whatsapp) : null;
  if (whatsapp && chat) {
    actions.push({
      kind: "whatsapp",
      href: chat,
      label: `WhatsApp ${shopName} on ${formatPhone(whatsapp)}`,
      text: "WhatsApp",
    });
  }
  if (email) {
    actions.push({
      kind: "email",
      href: emailHref(email),
      label: `Email ${shopName} at ${email}`,
      text: "Email",
    });
  }
  return actions;
}

/** Outlined buttons, one an action, with the icon of its kind. */
function ActionButtons({
  actions,
  shop,
  className,
}: {
  actions: Action[];
  shop: string;
  /** Classes for one button, by its place. */
  className?: (index: number) => string | undefined;
}) {
  return actions.map(({ kind, href, label, text }, index) => {
    const Icon = ICONS[kind];
    return (
      <ContactLink
        key={kind}
        kind={kind}
        shop={shop}
        href={href}
        aria-label={label}
        // The address on hover, for a desktop with no mail app to open.
        title={kind === "email" ? href.slice("mailto:".length) : undefined}
        className={cn(BUTTON, className?.(index))}
      >
        <Icon aria-hidden="true" className="size-4" />
        <span className={kind === "phone" ? "tabular" : undefined}>{text}</span>
      </ContactLink>
    );
  });
}

/**
 * The buttons in a row: "Call 02 2345 6789", then `extra` (the shop page's
 * other numbers, "or 02 2345 6780"), then WhatsApp and Email. On a phone the
 * call takes the width and the rest go in pairs under it, one left over taking
 * a row, so a row never ends in a stray button; from `sm` they are one row.
 */
export function ContactActionsRow({
  actions,
  shop,
  extra,
  className,
}: {
  actions: Action[];
  shop: string;
  extra?: ReactNode;
  className?: string;
}) {
  const call = actions.filter((action) => action.kind === "phone");
  const rest = actions.filter((action) => action.kind !== "phone");
  return (
    <div
      data-contact-actions
      className={cn(
        "grid grid-cols-2 items-center gap-2 *:justify-center sm:flex sm:flex-wrap sm:*:justify-start",
        className,
      )}
    >
      <ActionButtons actions={call} shop={shop} className={() => "col-span-2"} />
      {extra}
      <ActionButtons
        actions={rest}
        shop={shop}
        className={(index) =>
          rest.length % 2 === 1 && index === rest.length - 1 ? "col-span-2" : undefined
        }
      />
    </div>
  );
}

/**
 * "Contact Volt Corner directly": outlined "Call 02 2345 6789", WhatsApp and
 * Email buttons, whichever the shop publishes, for the one-shop product page,
 * under "Sold by", and its opening hours under them when known. Nothing at all
 * when it publishes no way to be reached. 44px tall on phones (S4).
 */
export function ContactButtons({
  reach,
  shop,
  shopName,
  hours = [],
  className,
}: {
  reach: ShopReach | null | undefined;
  shop: string;
  shopName: string;
  /** The shop's opening hours, as the API serves them. */
  hours?: string[];
  className?: string;
}) {
  if (!isReachable(reach)) return null;
  const actions = contactActions(reach, shopName);
  if (actions.length === 0) return null;
  return (
    <div data-contact-links="buttons" className={className}>
      <p className="text-[13px] text-ink-2">Contact {shopName} directly</p>
      <ContactActionsRow actions={actions} shop={shop} className="mt-1.5" />
      <HoursLine hours={hours} className="mt-2 text-[13px]" />
    </div>
  );
}

/**
 * The shops behind a product's offers, once each, with how to reach them, a
 * shop to a block: its name, then "Call 02 2345 6789 · WhatsApp · Email",
 * then its opening hours when known. Stacked rather than name-left,
 * links-right: in the narrow column a long name and three links do not fit on
 * one line, and a list whose rows break in different places reads ragged.
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
  shops: {
    slug: string;
    name: string;
    reach: ShopReach | null | undefined;
    hours?: string[];
  }[];
  className?: string;
}) {
  const reachable = shops.flatMap((shop) =>
    isReachable(shop.reach) ? [{ ...shop, actions: contactActions(shop.reach, shop.name) }] : [],
  );
  if (!reachable.some((shop) => shop.actions.length > 0)) return null;
  return (
    <section
      data-contact-links="shops"
      aria-labelledby="shop-contacts-heading"
      className={className}
    >
      <h3 id="shop-contacts-heading" className="text-[15px] text-ink">
        Contact the shops
      </h3>
      <ul className="mt-1 text-[13px] leading-snug">
        {reachable.map(({ slug, name, actions, hours }) => (
          <li
            key={slug}
            data-shop-contact-line={slug}
            className="flex flex-col gap-1 border-b border-line py-2.5 last:border-b-0"
          >
            <span className="font-semibold text-ink">{name}</span>
            <Dotted>
              {actions.map(({ kind, href, label, text }) => {
                const Icon = ICONS[kind];
                return (
                  <ContactLink
                    key={kind}
                    kind={kind}
                    shop={slug}
                    href={href}
                    aria-label={label}
                    className={cn(INLINE_LINK, "whitespace-nowrap")}
                  >
                    <Icon aria-hidden="true" className="me-1 inline size-3.5 align-[-2px]" />
                    {text}
                  </ContactLink>
                );
              })}
            </Dotted>
            <HoursLine hours={hours ?? []} />
          </li>
        ))}
      </ul>
    </section>
  );
}
