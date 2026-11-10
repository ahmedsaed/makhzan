import type { ReactNode } from "react";

import { ContactLink } from "@/components/contact-links";
import { SectionHeading } from "@/components/section";
import type { ShopBranch, ShopContact } from "@/lib/api";
import { formatPhone, mailtoHref, sourceLines, telHref, whatsappHref } from "@/lib/contact";
import { cn } from "@/lib/utils";

/**
 * How to reach a shop, as the shop itself publishes it: its numbers as `tel:`
 * links, WhatsApp, email, its address (and branches) with the shop's own map
 * link, and its opening hours. Text is the shop's own, in whatever language it
 * wrote it, hence `dir="auto"`.
 *
 * Under it, quietly, where the details came from and when they were checked:
 * a person reading the shop's site, or the crawler reading its structured
 * data. Nothing renders for a shop nobody has found anything for; the line at
 * the foot of the page says what is missing.
 */
export function ShopContactSection({
  contact,
  shop,
  shopName,
  websiteUrl,
  className,
}: {
  contact: ShopContact;
  shop: string;
  shopName: string;
  websiteUrl: string | null;
  className?: string;
}) {
  const blocks: ReactNode[] = [];
  const mainPlace = [contact.area, contact.governorate].filter(Boolean).join(", ");

  if (contact.phones.length > 0) {
    blocks.push(
      <Block key="phone" label={contact.phones.length > 1 ? "Phones" : "Phone"} kind="phone">
        {contact.phones.map((number) => (
          <Phone key={number} number={number} shop={shop} shopName={shopName} />
        ))}
      </Block>,
    );
  }
  const whatsapp = contact.whatsapp ? whatsappHref(contact.whatsapp) : null;
  if (contact.whatsapp && whatsapp) {
    blocks.push(
      <Block key="whatsapp" label="WhatsApp" kind="whatsapp">
        <ContactLink
          kind="whatsapp"
          shop={shop}
          href={whatsapp}
          aria-label={`WhatsApp ${shopName} on ${formatPhone(contact.whatsapp)}`}
          className={LINK}
        >
          <span className="tabular">{formatPhone(contact.whatsapp)}</span>
        </ContactLink>
      </Block>,
    );
  }
  if (contact.email) {
    blocks.push(
      <Block key="email" label="Email" kind="email">
        <ContactLink
          kind="email"
          shop={shop}
          href={mailtoHref(contact.email)}
          className={cn(LINK, "break-all")}
        >
          {contact.email}
        </ContactLink>
      </Block>,
    );
  }
  if (contact.address || mainPlace) {
    blocks.push(
      <Block
        key="address"
        label={contact.branches.length > 0 ? "Main shop" : "Address"}
        kind="address"
      >
        <Place
          address={contact.address}
          place={mainPlace}
          mapsUrl={contact.maps_url}
          shop={shop}
          shopName={shopName}
        />
      </Block>,
    );
  }
  contact.branches.forEach((branch, index) => {
    blocks.push(
      <Block key={`branch-${index}`} label={branch.name ?? "Branch"} kind="branch">
        <Branch branch={branch} shop={shop} shopName={shopName} />
      </Block>,
    );
  });
  if (contact.opening_hours.length > 0) {
    blocks.push(
      <Block key="hours" label="Opening hours" kind="hours">
        <ul className="text-[15px] leading-snug text-ink lg:text-sm">
          {contact.opening_hours.map((line) => (
            <li key={line} dir="auto">
              {line}
            </li>
          ))}
        </ul>
      </Block>,
    );
  }
  if (blocks.length === 0) return null;
  const sources = sourceLines(contact, shopName, websiteUrl);

  return (
    <section data-shop-contact aria-labelledby="shop-contact-heading" className={className}>
      <SectionHeading
        id="shop-contact-heading"
        className="lg:mb-2 lg:font-sans lg:text-[13px] lg:font-semibold lg:text-ink-2"
      >
        Contact
      </SectionHeading>
      <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">{blocks}</div>
      {sources.length > 0 && (
        <p data-contact-source className="mt-2 text-[13px] leading-relaxed text-ink-2">
          {sources.join(" ")}
        </p>
      )}
    </section>
  );
}

/** A text link, 44px to tap on phones (S4) though it reads as a line of text. */
const LINK = "inline-flex min-h-11 items-center font-semibold text-link hover:underline lg:min-h-0";

function Block({ label, kind, children }: { label: string; kind: string; children: ReactNode }) {
  return (
    <div data-contact-block={kind} className="flex min-w-0 flex-col">
      <span className="text-xs text-ink-2" dir="auto">
        {label}
      </span>
      <div className="mt-0.5 flex min-w-0 flex-col items-start">{children}</div>
    </div>
  );
}

function Phone({ number, shop, shopName }: { number: string; shop: string; shopName: string }) {
  const href = telHref(number);
  const text = formatPhone(number);
  if (!href) return <span className="text-[15px] text-ink tabular lg:text-sm">{text}</span>;
  return (
    <ContactLink
      kind="phone"
      shop={shop}
      href={href}
      aria-label={`Call ${shopName} on ${text}`}
      className={LINK}
    >
      <span className="tabular">{text}</span>
    </ContactLink>
  );
}

function Place({
  address,
  place,
  mapsUrl,
  shop,
  shopName,
  children,
}: {
  address: string | null;
  place: string;
  mapsUrl: string | null;
  shop: string;
  shopName: string;
  /** A branch's numbers: under its address, above its map link. */
  children?: ReactNode;
}) {
  return (
    <>
      {address && (
        <span dir="auto" className="text-[15px] leading-snug text-ink lg:text-sm">
          {address}
        </span>
      )}
      {place && (
        <span dir="auto" className="text-[13px] leading-snug text-ink-2">
          {place}
        </span>
      )}
      {children}
      {mapsUrl && (
        <ContactLink
          kind="map"
          shop={shop}
          href={mapsUrl}
          aria-label={`Map: ${shopName}${place ? `, ${place}` : ""}`}
          className={cn(LINK, "text-[13px]")}
        >
          Open in maps
        </ContactLink>
      )}
    </>
  );
}

function Branch({
  branch,
  shop,
  shopName,
}: {
  branch: ShopBranch;
  shop: string;
  shopName: string;
}) {
  const place = [branch.area, branch.governorate].filter(Boolean).join(", ");
  return (
    <>
      <Place
        address={branch.address}
        place={place}
        mapsUrl={branch.maps_url}
        shop={shop}
        shopName={branch.name ? `${shopName} ${branch.name}` : shopName}
      >
        {branch.phones.map((number) => (
          <Phone key={number} number={number} shop={shop} shopName={shopName} />
        ))}
      </Place>
    </>
  );
}
