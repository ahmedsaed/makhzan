import type { ReactNode } from "react";

import { ContactLink, ReportLink, TEXT_LINK } from "@/components/contact-links";
import { SectionHeading } from "@/components/section";
import type { ShopBranch, ShopContact } from "@/lib/api";
import { emailHref, formatPhone, provenance, telHref, whatsappHref } from "@/lib/contact";
import { cn } from "@/lib/utils";

/**
 * How to reach a shop, as its details are published (its site, its Facebook,
 * its Google Maps listing): its numbers as `tel:` links, WhatsApp, email, its
 * address (and branches) with a map link, and its opening hours. Text is as
 * published, in whatever language, hence `dir="auto"`.
 *
 * Under it, quietly, one sentence on where each detail came from and when it
 * was checked ("Phone and email from Nile Parts' website and address from Google
 * Maps, all checked 10 Nov 2026."), then "Something wrong? Tell us". Nothing
 * renders for a shop nobody has found anything for; the line at the foot of
 * the page says what is missing.
 */
export function ShopContactSection({
  contact,
  shop,
  shopName,
  websiteUrl,
  page,
  className,
}: {
  contact: ShopContact;
  shop: string;
  shopName: string;
  websiteUrl: string | null;
  /** The shop page's absolute URL, for the report email. */
  page: string;
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
          href={emailHref(contact.email)}
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
  const source = provenance(contact, shopName, websiteUrl);

  return (
    <section data-shop-contact aria-labelledby="shop-contact-heading" className={className}>
      <SectionHeading
        id="shop-contact-heading"
        className="lg:mb-2 lg:font-sans lg:text-[13px] lg:font-semibold lg:text-ink-2"
      >
        Contact
      </SectionHeading>
      <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">{blocks}</div>
      {source && (
        <p data-contact-source className="mt-2 text-[13px] leading-relaxed text-ink-2">
          {source}
        </p>
      )}
      <ReportLink shop={shop} shopName={shopName} page={page} />
    </section>
  );
}

const LINK = TEXT_LINK;

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
  // "Call Shop A Giza branch on …": which of the shop's places the number rings.
  const label = branch.name ? `${shopName} ${branch.name}` : shopName;
  return (
    <Place
      address={branch.address}
      place={place}
      mapsUrl={branch.maps_url}
      shop={shop}
      shopName={label}
    >
      {branch.phones.map((number) => (
        <Phone key={number} number={number} shop={shop} shopName={label} />
      ))}
    </Place>
  );
}
